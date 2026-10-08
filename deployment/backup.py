"""Consistent SQLite snapshots plus original captions, encrypted in private S3."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tarfile
import tempfile

import boto3


def make_backup(data_dir, destination):
    data_dir, destination = Path(data_dir), Path(destination)
    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        databases = []
        for name in ('channels.sqlite3', 'responses.sqlite3', 'accounts.sqlite3'):
            path = data_dir / name
            if path.exists():
                snapshot = work / name
                with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as source:
                    with sqlite3.connect(snapshot) as copied:
                        source.backup(copied)
                        if copied.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                            raise RuntimeError('A database backup failed its integrity check.')
                databases.append(snapshot)
        if not (work / 'channels.sqlite3').exists():
            raise RuntimeError('The archive catalog is missing; refusing an incomplete backup.')
        with tarfile.open(destination, 'w:gz') as archive:
            for path in databases:
                archive.add(path, arcname=path.name)
            captions = data_dir / 'supermemory-trial' / 'timed-captions'
            if not captions.is_dir():
                raise RuntimeError('The original captions are missing.')
            archive.add(captions, arcname='supermemory-trial/timed-captions')
            diagnostics = data_dir / 'response-diagnostics'
            if diagnostics.is_dir():
                archive.add(diagnostics, arcname='response-diagnostics')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--bucket', required=True)
    parser.add_argument('--region', required=True)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    with tempfile.TemporaryDirectory() as work:
        path = Path(work) / 'backup.tar.gz'
        make_backup(args.data_dir, path)
        s3 = boto3.client('s3', region_name=args.region)
        key = f'backups/{stamp}.tar.gz'
        s3.upload_file(str(path), args.bucket, key, ExtraArgs={'ServerSideEncryption': 'AES256'})
        result = s3.head_object(Bucket=args.bucket, Key=key)
        if result['ContentLength'] != path.stat().st_size:
            raise RuntimeError('Backup upload size could not be verified.')
    (args.data_dir / 'last-backup.json').write_text(json.dumps({'created_at': stamp, 'key': key}) + '\n')
    boto3.client('cloudwatch', region_name=args.region).put_metric_data(Namespace='KnowledgeReader',
        MetricData=[{'MetricName': 'BackupSucceeded', 'Value': 1, 'Unit': 'Count',
                     'Dimensions': [{'Name': 'BackupBucket', 'Value': args.bucket}]}])
    print('Backup stored and verified; contents and credentials omitted.')


if __name__ == '__main__':
    main()
