"""Health check without exposing the origin secret in command arguments or logs."""
import json
import os
import time
from urllib.parse import urlsplit

import boto3
import requests


def main():
    secret = boto3.client('secretsmanager', region_name=os.environ['AWS_REGION']).get_secret_value(
        SecretId=os.environ['APP_SECRET_ARN'])
    settings = json.loads(secret['SecretString'])
    headers = {'Host': urlsplit(settings['PUBLIC_BASE_URL']).netloc, 'X-Reader-Origin': settings['ORIGIN_SECRET']}
    for _ in range(30):
        try:
            response = requests.get('http://127.0.0.1:8000/health/ready', headers=headers, timeout=10)
            if response.status_code == 200 and response.json().get('ok') is True:
                print('Application and persistent archive are ready.')
                return
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2)
    raise SystemExit('Application health check failed. Check the service logs; no secrets were printed.')


if __name__ == '__main__':
    main()
