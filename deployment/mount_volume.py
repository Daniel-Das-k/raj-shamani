"""Mount only the stack-owned EBS volume; never format an existing filesystem."""
import json
from pathlib import Path
import re
import subprocess
import sys
import time


def mount(volume_id, destination='/var/lib/knowledge-reader'):
    if not re.fullmatch(r'vol-[a-f0-9]{8,32}', volume_id):
        raise ValueError('Invalid EBS volume ID.')
    serial = volume_id.replace('-', '')
    device = None
    for _ in range(60):
        disks = json.loads(subprocess.check_output(['lsblk', '--json', '--paths', '--output', 'NAME,SERIAL,FSTYPE,TYPE']))
        device = next((row for row in disks['blockdevices'] if (row.get('serial') or '').strip() == serial), None)
        if device:
            break
        time.sleep(5)
    if device is None or device['type'] != 'disk' or device.get('children'):
        raise RuntimeError('The dedicated, unpartitioned data volume could not be identified safely.')
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    if subprocess.run(['mountpoint', '-q', str(target)]).returncode == 0:
        mounted = subprocess.check_output(['findmnt', '-n', '-o', 'SOURCE', '--target', str(target)], text=True).strip()
        if Path(mounted).resolve() != Path(device['name']).resolve():
            raise RuntimeError('The data directory is mounted from an unexpected device.')
        return
    if device.get('fstype'):
        if device['fstype'] != 'ext4':
            raise RuntimeError('The data volume has an unexpected filesystem. It will not be changed.')
    else:
        # A volume with signatures/partitions must not be mistaken for a new empty disk.
        signatures = json.loads(subprocess.check_output(['wipefs', '--json', device['name']]))
        if signatures.get('signatures'):
            raise RuntimeError('The data volume contains existing signatures. It will not be formatted.')
        subprocess.run(['mkfs.ext4', device['name']], check=True)
    uuid = subprocess.check_output(['blkid', '-s', 'UUID', '-o', 'value', device['name']], text=True).strip()
    if not re.fullmatch(r'[a-f0-9-]+', uuid):
        raise RuntimeError('The volume UUID could not be verified.')
    fstab = Path('/etc/fstab')
    line = f'UUID={uuid} {target} ext4 defaults,nofail 0 2\n'
    previous = fstab.read_text()
    if any(str(target) in row.split() for row in previous.splitlines() if row and not row.startswith('#')):
        if line.strip() not in previous.splitlines():
            raise RuntimeError('An unexpected fstab entry already uses the data directory.')
    else:
        with fstab.open('a') as handle:
            handle.write('\n' + line)
    subprocess.run(['mount', str(target)], check=True)


if __name__ == '__main__':
    mount(sys.argv[1])
