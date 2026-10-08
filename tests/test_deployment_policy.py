import json
from fnmatch import fnmatchcase
from pathlib import Path
import re
import unittest

from deployment.template import template


class DeploymentPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = json.loads((Path(__file__).resolve().parents[1] /
                                 'deployment/knowledge-reader-deploy-policy.json').read_text())

    def test_resource_arns_use_literal_account_ids(self):
        # IAM substitution is supported only after an ARN's fifth colon.
        for statement in self.policy['Statement']:
            resources = statement['Resource']
            if isinstance(resources, str):
                resources = [resources]
            for arn in resources:
                if arn == '*':
                    continue
                with self.subTest(statement=statement['Sid'], resource=arn):
                    parts = arn.split(':', 5)
                    self.assertEqual(len(parts), 6)
                    self.assertEqual(parts[0], 'arn')
                    self.assertNotIn('${', ':'.join(parts[:5]))
                    self.assertTrue(re.fullmatch(r'(?:[0-9]{12}|aws)?', parts[4]))

    def test_document_fits_iam_customer_managed_policy_limit(self):
        self.assertEqual(self.policy['Version'], '2012-10-17')
        self.assertLessEqual(len(json.dumps(self.policy, separators=(',', ':'))), 6144)

    def test_explicit_resource_names_match_deployment_policy(self):
        statements = {s['Sid']: s for s in self.policy['Statement']}
        account = statements['DeployNamedStackInMumbai']['Resource'].split(':')[4]
        resources = template()['Resources']
        for logical, prop, policy_sid, arn in [
            ('Storage', 'BucketName', 'ManageNamedStorage', 'arn:aws:s3:::{name}'),
            ('Settings', 'Name', 'ManageNamedAppSecret', 'arn:aws:secretsmanager:ap-south-1:{account}:secret:{name}-AbCdEf'),
            ('AppLogs', 'LogGroupName', 'ManageNamedLogsViaCloudFormation', 'arn:aws:logs:ap-south-1:{account}:log-group:{name}:*'),
            ('RuntimeRole', 'RoleName', 'ManageNamedRoleAndInstanceProfileViaCloudFormation', 'arn:aws:iam::{account}:role/{name}'),
            ('RuntimeProfile', 'InstanceProfileName', 'ManageNamedRoleAndInstanceProfileViaCloudFormation', 'arn:aws:iam::{account}:instance-profile/{name}'),
            ('InstanceAlarm', 'AlarmName', 'ManageNamedAlarmsViaCloudFormation', 'arn:aws:cloudwatch:ap-south-1:{account}:alarm:{name}'),
            ('BackupAlarm', 'AlarmName', 'ManageNamedAlarmsViaCloudFormation', 'arn:aws:cloudwatch:ap-south-1:{account}:alarm:{name}'),
        ]:
            with self.subTest(resource=logical):
                name = resources[logical]['Properties'][prop]['Fn::Sub']
                name = name.replace('${AWS::StackName}', 'knowledge-reader').replace('${AWS::AccountId}', account)
                resource_arn = arn.format(name=name, account=account)
                patterns = statements[policy_sid]['Resource']
                if isinstance(patterns, str):
                    patterns = [patterns]
                self.assertTrue(any(fnmatchcase(resource_arn, p) for p in patterns), resource_arn)


if __name__ == '__main__':
    unittest.main()
