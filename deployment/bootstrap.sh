#!/bin/bash
# Invoked through SSM with resource IDs only. Provider keys never enter shell text.
set -euo pipefail
release_dir=$1
data_volume=$2
app_secret=$3
aws_region=$4
backup_bucket=$5
log_group=$6

dnf install -y python3.12 python3.12-pip amazon-cloudwatch-agent
python3.12 "$release_dir/deployment/mount_volume.py" "$data_volume"
if ! id knowledge-reader >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/knowledge-reader --shell /sbin/nologin knowledge-reader
fi
mkdir -p /var/lib/knowledge-reader/data /etc/knowledge-reader
chmod 700 /etc/knowledge-reader
python3.12 -m venv "$release_dir/.venv"
"$release_dir/.venv/bin/python" -m pip install --disable-pip-version-check -r "$release_dir/requirements-production.txt"
cd "$release_dir"
"$release_dir/.venv/bin/python" -m deployment.seed seed-data /var/lib/knowledge-reader/data
chown -R knowledge-reader:knowledge-reader /var/lib/knowledge-reader
chmod 700 /var/lib/knowledge-reader/data

# EnvironmentFile contains nonsecret locations only. Runtime fetches Secrets Manager.
cat > /etc/knowledge-reader/deployment.env <<EOF
AWS_REGION=$aws_region
APP_SECRET_ARN=$app_secret
BACKUP_BUCKET=$backup_bucket
DATA_DIR=/var/lib/knowledge-reader/data
PYTHONDONTWRITEBYTECODE=1
PYTHONUNBUFFERED=1
EOF
chmod 600 /etc/knowledge-reader/deployment.env
previous_release=$(readlink -f /opt/knowledge-reader/current || true)
ln -sfn "$release_dir" /opt/knowledge-reader/current
cat > /etc/systemd/system/knowledge-reader.service <<'EOF'
[Unit]
Description=Knowledge Reader public application
After=network-online.target
Wants=network-online.target
RequiresMountsFor=/var/lib/knowledge-reader

[Service]
User=knowledge-reader
Group=knowledge-reader
WorkingDirectory=/opt/knowledge-reader/current
EnvironmentFile=/etc/knowledge-reader/deployment.env
ExecStart=/opt/knowledge-reader/current/.venv/bin/python -m deployment.runtime
Restart=on-failure
RestartSec=5
TimeoutStopSec=320
KillSignal=SIGTERM
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/knowledge-reader
UMask=0077
StandardOutput=append:/var/log/knowledge-reader.log
StandardError=append:/var/log/knowledge-reader.log

[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/knowledge-reader-backup.service <<'EOF'
[Unit]
Description=Knowledge Reader consistent backup to private S3
After=network-online.target
RequiresMountsFor=/var/lib/knowledge-reader

[Service]
Type=oneshot
User=knowledge-reader
Group=knowledge-reader
WorkingDirectory=/opt/knowledge-reader/current
EnvironmentFile=/etc/knowledge-reader/deployment.env
ExecStart=/opt/knowledge-reader/current/.venv/bin/python -m deployment.backup --data-dir ${DATA_DIR} --bucket ${BACKUP_BUCKET} --region ${AWS_REGION}
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/knowledge-reader
UMask=0077
EOF
cat > /etc/systemd/system/knowledge-reader-backup.timer <<'EOF'
[Unit]
Description=Daily Knowledge Reader backup

[Timer]
OnCalendar=*-*-* 02:00:00 UTC
RandomizedDelaySec=300
Persistent=true

[Install]
WantedBy=timers.target
EOF
cat > /etc/logrotate.d/knowledge-reader <<'EOF'
/var/log/knowledge-reader.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}
EOF
python3.12 - "$log_group" <<'PY'
import json, sys
from pathlib import Path
Path('/etc/knowledge-reader/cloudwatch.json').write_text(json.dumps({'logs': {'logs_collected': {'files': {'collect_list': [{
    'file_path': '/var/log/knowledge-reader.log', 'log_group_name': sys.argv[1], 'log_stream_name': '{instance_id}'
}]}}}}))
PY
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c file:/etc/knowledge-reader/cloudwatch.json -s
systemctl daemon-reload
systemctl enable knowledge-reader.service knowledge-reader-backup.timer
systemctl restart knowledge-reader.service
# Verify internally using the origin header loaded directly from Secrets Manager.
if ! AWS_REGION="$aws_region" APP_SECRET_ARN="$app_secret" "$release_dir/.venv/bin/python" -m deployment.check_runtime; then
    if [ -n "$previous_release" ] && [ "$previous_release" != "$release_dir" ]; then
        ln -sfn "$previous_release" /opt/knowledge-reader/current
        systemctl restart knowledge-reader.service
    fi
    exit 1
fi
systemctl start knowledge-reader-backup.service
systemctl start knowledge-reader-backup.timer
echo 'Reader installed, health checked and first backup completed.'
