"""Review/apply only the initial CloudFront ingress correction to an owned stack."""
import argparse
import copy
import json
import time
import uuid

from botocore.exceptions import ClientError

from .aws_deploy import ROOT, aws_session, cloudfront_prefix_list, wait_stack
from .template import template


def corrected_template(current):
    wanted = template()
    legacy = copy.deepcopy(wanted)
    del legacy['Parameters']['CloudFrontPrefixListId']
    legacy['Resources']['AppSecurityGroup']['Properties']['SecurityGroupIngress'] = [
        {'IpProtocol': 'tcp', 'FromPort': 8000, 'ToPort': 8000, 'CidrIp': '10.42.0.0/24'}]
    if current != legacy:
        raise RuntimeError('The existing stack differs from the expected initial template. Inspect it before updating.')
    return wanted


def check_changes(changes):
    if len(changes) != 1:
        raise RuntimeError('The change set must modify exactly one resource; it has not been executed.')
    resource = changes[0].get('ResourceChange', {})
    if (resource.get('LogicalResourceId') != 'AppSecurityGroup' or
            resource.get('ResourceType') != 'AWS::EC2::SecurityGroup' or
            resource.get('Action') != 'Modify' or resource.get('Replacement') != 'False' or
            resource.get('Scope') != ['Properties']):
        raise RuntimeError('Unexpected infrastructure change or replacement. The change set has not been executed.')
    details = resource.get('Details', [])
    if not details or any(item.get('Target', {}).get('Name') != 'SecurityGroupIngress' for item in details):
        raise RuntimeError('Only the CloudFront ingress property may change. The change set has not been executed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region', default='ap-south-1')
    parser.add_argument('--stack', default='knowledge-reader')
    parser.add_argument('--apply', action='store_true', help='Execute only after the strict resource change checks pass.')
    args = parser.parse_args()
    session = aws_session(region=args.region)
    client = session.client('cloudformation')
    stack = client.describe_stacks(StackName=args.stack)['Stacks'][0]
    if stack['StackStatus'] not in {'CREATE_COMPLETE', 'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE'}:
        raise RuntimeError('Wait for a stable stack before repairing ingress.')
    if not any(t['Key'] == 'Project' and t['Value'] == 'KnowledgeReader' for t in stack.get('Tags', [])):
        raise RuntimeError('Refusing to update an unrelated stack.')
    current = client.get_template(StackName=stack['StackId'])['TemplateBody']
    if isinstance(current, str):
        current = json.loads(current)
    if current == template():
        print('CloudFront ingress template is already current. Verify the public endpoint.')
        return
    wanted = corrected_template(current)
    prefix = cloudfront_prefix_list(session.client('ec2'))
    parameters = [{'ParameterKey': item['ParameterKey'], 'UsePreviousValue': True}
                  for item in stack.get('Parameters', [])]
    parameters.append({'ParameterKey': 'CloudFrontPrefixListId', 'ParameterValue': prefix})
    change_id = client.create_change_set(StackName=stack['StackId'],
        ChangeSetName='cloudfront-ingress-' + uuid.uuid4().hex[:12], ChangeSetType='UPDATE',
        Description='Admit AWS-managed CloudFront origin-facing traffic on port 8000.',
        TemplateBody=json.dumps(wanted), Capabilities=['CAPABILITY_NAMED_IAM'],
        Parameters=parameters, Tags=stack.get('Tags', []))['Id']
    print('Preparing the CloudFront ingress change set…', flush=True)
    for _ in range(120):
        review = client.describe_change_set(StackName=stack['StackId'], ChangeSetName=change_id)
        if review['Status'] == 'CREATE_COMPLETE':
            break
        if review['Status'] == 'FAILED':
            raise RuntimeError('Change set preparation failed: ' + review.get('StatusReason', 'unknown reason'))
        time.sleep(5)
    else:
        raise RuntimeError('Change set still preparing; it has not been executed.')
    changes = review.get('Changes', [])
    while review.get('NextToken'):
        review = client.describe_change_set(StackName=stack['StackId'], ChangeSetName=change_id, NextToken=review['NextToken'])
        changes.extend(review.get('Changes', []))
    directory = ROOT / '.deployment'
    directory.mkdir(exist_ok=True)
    (directory / 'cloudfront-ingress-change.json').write_text(json.dumps(
        {'stack_id': stack['StackId'], 'change_set': change_id, 'prefix_list': prefix, 'changes': changes}, indent=2) + '\n')
    check_changes(changes)
    print('Verified: one ingress update; no server, disk, database or identity resource replacements.', flush=True)
    if not args.apply:
        print('Reviewed change set saved. It has not been executed.')
        return
    client.execute_change_set(StackName=stack['StackId'], ChangeSetName=change_id)
    # Wait until execution has actually begun, so the previous CREATE_COMPLETE is
    # never mistaken for a completed update by wait_stack.
    for _ in range(60):
        status = client.describe_change_set(StackName=stack['StackId'], ChangeSetName=change_id)['ExecutionStatus']
        current_status = client.describe_stacks(StackName=stack['StackId'])['Stacks'][0]['StackStatus']
        if status == 'EXECUTE_COMPLETE' or (status == 'EXECUTE_IN_PROGRESS' and current_status != stack['StackStatus']):
            break
        if status == 'UNAVAILABLE':
            raise RuntimeError('Change set execution is unavailable; inspect the stack.')
        time.sleep(2)
    else:
        raise RuntimeError('Change set execution did not start; inspect the stack.')
    outputs = wait_stack(client, stack['StackId'])
    print('CloudFront ingress updated. Verify: ' + outputs['URL'])


if __name__ == '__main__':
    try:
        main()
    except ClientError as exc:
        code = exc.response.get('Error', {}).get('Code', 'ClientError')
        if code in {'AccessDenied', 'AccessDeniedException', 'UnauthorizedOperation'}:
            raise SystemExit(f'AWS denied {exc.operation_name} ({code}). Update the existing KnowledgeReaderDeploy policy from the local JSON file. Existing resources are preserved.') from None
        raise
