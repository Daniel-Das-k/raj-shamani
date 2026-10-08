import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from deployment.aws_deploy import failure_reasons, recover_failed_stack


class DeploymentRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.stack = {'StackId': 'failed-stack-id', 'StackStatus': 'ROLLBACK_COMPLETE',
                      'Tags': [{'Key': 'Project', 'Value': 'KnowledgeReader'}]}
        self.resources = [{'LogicalResourceId': 'Storage', 'PhysicalResourceId': 'retained-bucket',
                           'ResourceType': 'AWS::S3::Bucket', 'ResourceStatus': 'DELETE_SKIPPED'}]
        self.client.get_paginator.return_value.paginate.return_value = [
            {'StackResourceSummaries': self.resources}]
        self.client.get_template.return_value = {'TemplateBody': {
            'Resources': {'Storage': {'DeletionPolicy': 'Retain'}}}}
        self.client.describe_stacks.return_value = {'Stacks': [{'StackStatus': 'DELETE_COMPLETE'}]}

    def test_recovers_failed_initial_stack_and_records_retained_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            recover_failed_stack(self.client, self.stack, Path(directory))
            record = json.loads((Path(directory) / 'failed-stack-resources.json').read_text())
        self.assertEqual(record['resources'][0]['PhysicalResourceId'], 'retained-bucket')
        self.client.update_termination_protection.assert_called_once_with(
            StackName='failed-stack-id', EnableTerminationProtection=False)
        self.client.delete_stack.assert_called_once_with(StackName='failed-stack-id')
        self.assertLess([c[0] for c in self.client.mock_calls].index('update_termination_protection'),
                        [c[0] for c in self.client.mock_calls].index('delete_stack'))

    def test_refuses_healthy_in_progress_and_unrelated_stacks(self):
        for changes in [{'StackStatus': 'CREATE_COMPLETE'}, {'StackStatus': 'ROLLBACK_IN_PROGRESS'},
                        {'Tags': []}]:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(RuntimeError):
                    recover_failed_stack(self.client, {**self.stack, **changes}, Path(directory))
        self.client.delete_stack.assert_not_called()
        self.client.update_termination_protection.assert_not_called()

    def test_refuses_stacks_that_created_a_server_or_data_disk(self):
        for logical_id in ['Instance', 'DataVolume']:
            self.client.get_paginator.return_value.paginate.return_value = [
                {'StackResourceSummaries': [{'LogicalResourceId': logical_id,
                                            'PhysicalResourceId': 'existing-data'}]}]
            with self.subTest(logical_id=logical_id), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(RuntimeError, 'server or data disk'):
                    recover_failed_stack(self.client, self.stack, Path(directory))
        self.client.delete_stack.assert_not_called()
        self.client.update_termination_protection.assert_not_called()

    def test_refuses_deleting_persistent_resources_without_retention(self):
        self.client.get_template.return_value = {'TemplateBody': {'Resources': {'Storage': {}}}}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, 'retention policy'):
                recover_failed_stack(self.client, self.stack, Path(directory))
        self.client.delete_stack.assert_not_called()
        self.client.update_termination_protection.assert_not_called()

    def test_root_failure_is_not_hidden_by_cancelled_resources(self):
        events = [{'LogicalResourceId': 'Cancelled' + str(i), 'ResourceStatus': 'CREATE_FAILED',
                   'ResourceStatusReason': 'Resource creation cancelled'} for i in range(10)]
        events.append({'LogicalResourceId': 'Settings', 'ResourceStatus': 'CREATE_FAILED',
                       'ResourceStatusReason': 'AccessDenied: CreateSecret'})
        self.assertEqual(failure_reasons(events), ['Settings: AccessDenied: CreateSecret'])


if __name__ == '__main__':
    unittest.main()
