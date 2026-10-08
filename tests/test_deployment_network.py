import copy
import unittest
from unittest.mock import Mock

from deployment.aws_deploy import cloudfront_prefix_list, provider_configuration
from deployment.repair_cloudfront import corrected_template, check_changes
from deployment.template import template


class DeploymentNetworkTests(unittest.TestCase):
    def test_explicit_provider_key_replaces_stale_inherited_key(self):
        values = provider_configuration({'OPENAI_API_KEY': 'test-new-project-key'},
            {'OPENAI_API_KEY': 'test-stale-inherited-key', 'SUPERMEMORY_API_KEY': 'test-index-key'})
        self.assertEqual(values['OPENAI_API_KEY'], 'test-new-project-key')
        self.assertEqual(values['SUPERMEMORY_API_KEY'], 'test-index-key')
        self.assertNotIn('OPENAI_CHAT_MODEL', values)

    def test_prefix_lookup_rejects_customer_owned_or_ambiguous_lists(self):
        client = Mock()
        row = {'PrefixListId': 'pl-abcdef', 'OwnerId': 'AWS', 'AddressFamily': 'IPv4',
               'PrefixListName': 'com.amazonaws.global.cloudfront.origin-facing'}
        paginator = client.get_paginator.return_value
        paginator.paginate.return_value = [{'PrefixLists': [row]}]
        self.assertEqual(cloudfront_prefix_list(client), 'pl-abcdef')
        for rows in ([], [row, row], [{**row, 'OwnerId': '123456789012'}], [{**row, 'AddressFamily': 'IPv6'}]):
            paginator.paginate.return_value = [{'PrefixLists': rows}]
            with self.assertRaises(RuntimeError):
                cloudfront_prefix_list(client)

    def test_repair_refuses_any_unrelated_template_difference(self):
        old = template()
        del old['Parameters']['CloudFrontPrefixListId']
        old['Resources']['AppSecurityGroup']['Properties']['SecurityGroupIngress'] = [
            {'IpProtocol': 'tcp', 'FromPort': 8000, 'ToPort': 8000, 'CidrIp': '10.42.0.0/24'}]
        self.assertEqual(corrected_template(old), template())
        old['Resources']['DataVolume']['Properties']['Size'] = 40
        with self.assertRaises(RuntimeError):
            corrected_template(old)

    def test_change_review_refuses_replacements_additions_or_non_ingress_changes(self):
        change = {'ResourceChange': {'LogicalResourceId': 'AppSecurityGroup', 'ResourceType': 'AWS::EC2::SecurityGroup',
            'Action': 'Modify', 'Replacement': 'False', 'Scope': ['Properties'],
            'Details': [{'Target': {'Name': 'SecurityGroupIngress'}}]}}
        check_changes([change])
        for changes in ([], [change, change], [{'ResourceChange': {**change['ResourceChange'], 'Replacement': 'True'}}],
                        [{'ResourceChange': {**change['ResourceChange'], 'LogicalResourceId': 'Instance'}}]):
            with self.assertRaises(RuntimeError):
                check_changes(changes)
        wrong = copy.deepcopy(change)
        wrong['ResourceChange']['Details'][0]['Target']['Name'] = 'GroupDescription'
        with self.assertRaises(RuntimeError):
            check_changes([wrong])


if __name__ == '__main__':
    unittest.main()
