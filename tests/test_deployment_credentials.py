import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError

from deployment import aws_deploy


class DeploymentCredentialsTests(unittest.TestCase):
    def test_google_credentials_stay_paired_and_fail_before_deployment_when_incomplete(self):
        complete = {'GOOGLE_CLIENT_ID': 'test.apps.googleusercontent.com', 'GOOGLE_CLIENT_SECRET': 'synthetic-secret'}
        self.assertEqual(aws_deploy.auth_configuration(complete), {'PUBLIC_AUTH_MODE': 'google', **complete})
        self.assertEqual(aws_deploy.auth_configuration({'PUBLIC_AUTH_MODE': 'cognito'}), {'PUBLIC_AUTH_MODE': 'cognito'})
        for partial in [{'GOOGLE_CLIENT_ID': complete['GOOGLE_CLIENT_ID']},
                        {'GOOGLE_CLIENT_SECRET': complete['GOOGLE_CLIENT_SECRET']}]:
            combined = aws_deploy.provider_configuration(partial, complete)
            with self.assertRaises(ValueError):
                aws_deploy.auth_configuration(combined)
        self.assertEqual(aws_deploy.provider_configuration(complete, {'GOOGLE_CLIENT_SECRET': 'wrong'}), complete)

    def session_kwargs(self, file_values=None, environ=None, **options):
        with patch.object(aws_deploy.boto3, 'Session') as create:
            aws_deploy.aws_session(file_values=file_values or {}, environ=environ or {}, **options)
        return create.call_args.kwargs

    def test_reads_dotenv_key_pair_and_matching_temporary_token(self):
        kwargs = self.session_kwargs(file_values={
            'AWS_ACCESS_KEY_ID': 'file-id', 'AWS_SECRET_ACCESS_KEY': 'file-secret',
            'AWS_SESSION_TOKEN': 'file-token', 'AWS_DEFAULT_REGION': 'eu-west-1',
        })
        self.assertEqual(kwargs, {'aws_access_key_id': 'file-id',
                                 'aws_secret_access_key': 'file-secret',
                                 'aws_session_token': 'file-token', 'region_name': 'eu-west-1'})

    def test_process_pair_wins_without_importing_file_session_token(self):
        kwargs = self.session_kwargs(
            file_values={'AWS_ACCESS_KEY_ID': 'file-id', 'AWS_SECRET_ACCESS_KEY': 'file-secret',
                         'AWS_SESSION_TOKEN': 'file-token'},
            environ={'AWS_ACCESS_KEY_ID': 'env-id', 'AWS_SECRET_ACCESS_KEY': 'env-secret'})
        self.assertEqual(kwargs['aws_access_key_id'], 'env-id')
        self.assertEqual(kwargs['aws_secret_access_key'], 'env-secret')
        self.assertIsNone(kwargs['aws_session_token'])

    def test_explicit_profile_ignores_even_incomplete_local_keys(self):
        kwargs = self.session_kwargs(profile='deployment',
                                     environ={'AWS_SESSION_TOKEN': 'unrelated-token'},
                                     file_values={'AWS_ACCESS_KEY_ID': 'incomplete'})
        self.assertEqual(kwargs, {'profile_name': 'deployment', 'region_name': 'ap-south-1'})

    def test_empty_placeholders_leave_standard_sdk_credentials_available(self):
        kwargs = self.session_kwargs(file_values={'AWS_ACCESS_KEY_ID': '',
            'AWS_SECRET_ACCESS_KEY': None, 'AWS_SESSION_TOKEN': ''})
        self.assertEqual(kwargs, {'region_name': 'ap-south-1'})

    def test_incomplete_credentials_never_fall_back_or_combine(self):
        valid = {'AWS_ACCESS_KEY_ID': 'complete-id', 'AWS_SECRET_ACCESS_KEY': 'complete-secret'}
        for partial in [{'AWS_ACCESS_KEY_ID': 'partial-id'},
                        {'AWS_SECRET_ACCESS_KEY': 'partial-secret'},
                        {'AWS_SESSION_TOKEN': 'partial-token'}]:
            for environ, file_values, source in [(partial, valid, 'process environment'),
                                                 ({}, partial, 'local .env')]:
                with self.subTest(partial=partial, source=source):
                    with patch.object(aws_deploy.boto3, 'Session') as create:
                        with self.assertRaisesRegex(ValueError, 'Incomplete AWS credentials') as error:
                            aws_deploy.aws_session(environ=environ, file_values=file_values)
                        create.assert_not_called()
                    self.assertIn(source, str(error.exception))
                    for value in partial.values():
                        self.assertNotIn(value, str(error.exception))

    def test_region_cli_then_environment_then_file_then_mumbai(self):
        file_values = {'AWS_REGION': 'eu-west-1', 'AWS_DEFAULT_REGION': 'eu-west-2'}
        environ = {'AWS_REGION': 'us-east-1', 'AWS_DEFAULT_REGION': 'us-east-2'}
        self.assertEqual(self.session_kwargs(file_values, environ, region='ap-south-2')['region_name'],
                         'ap-south-2')
        self.assertEqual(self.session_kwargs(file_values, environ)['region_name'], 'us-east-1')
        self.assertEqual(self.session_kwargs(file_values, {'AWS_DEFAULT_REGION': 'us-east-2'})['region_name'],
                         'us-east-2')
        self.assertEqual(self.session_kwargs(file_values)['region_name'], 'eu-west-1')
        self.assertEqual(self.session_kwargs()['region_name'], 'ap-south-1')

    def test_dotenv_credentials_are_literal_and_do_not_modify_process_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text('AWS_ACCESS_KEY_ID=file-id\n'
                                      'AWS_SECRET_ACCESS_KEY="literal-${UNRELATED}"\n')
            with patch.object(aws_deploy, 'ROOT', root), \
                    patch.dict(aws_deploy.os.environ, {'UNRELATED': 'expanded'}, clear=True), \
                    patch.object(aws_deploy.boto3, 'Session') as create:
                aws_deploy.aws_session()
                self.assertEqual(create.call_args.kwargs['aws_secret_access_key'], 'literal-${UNRELATED}')
                self.assertNotIn('AWS_ACCESS_KEY_ID', aws_deploy.os.environ)

    def test_check_aws_calls_only_sts_without_packaging_or_provisioning(self):
        session = Mock(region_name='ap-south-1')
        session.client.return_value.get_caller_identity.return_value = {'Account': '123456789012'}
        output = io.StringIO()
        with patch('sys.argv', ['aws_deploy', '--check-aws']), \
                patch.object(aws_deploy, 'dotenv_values', return_value={}), \
                patch.object(aws_deploy, 'aws_session', return_value=session), \
                patch.object(aws_deploy, 'package') as package, contextlib.redirect_stdout(output):
            aws_deploy.main()
        package.assert_not_called()
        session.client.assert_called_once_with('sts')
        session.client.return_value.get_caller_identity.assert_called_once_with()
        self.assertIn('account ending 9012', output.getvalue())
        self.assertNotIn('123456789012', output.getvalue())
        self.assertIn('No resources were created', output.getvalue())

    def test_failed_check_does_not_print_aws_error_payload_or_package(self):
        session = Mock()
        session.client.return_value.get_caller_identity.side_effect = ClientError(
            {'Error': {'Code': 'InvalidClientTokenId', 'Message': 'sensitive-error-detail'}},
            'GetCallerIdentity')
        with patch('sys.argv', ['aws_deploy', '--check-aws']), \
                patch.object(aws_deploy, 'dotenv_values', return_value={}), \
                patch.object(aws_deploy, 'aws_session', return_value=session), \
                patch.object(aws_deploy, 'package') as package:
            with self.assertRaises(SystemExit) as error:
                aws_deploy.main()
        package.assert_not_called()
        self.assertIn('InvalidClientTokenId', str(error.exception))
        self.assertNotIn('sensitive-error-detail', str(error.exception))

    def test_deployment_permission_error_names_operation_without_aws_payload(self):
        denied = ClientError({'Error': {'Code': 'AccessDenied', 'Message': 'private-aws-payload'}},
                             'ValidateTemplate')
        with patch.object(aws_deploy, 'main', side_effect=denied):
            with self.assertRaises(SystemExit) as error:
                aws_deploy.run_cli()
        self.assertIn('ValidateTemplate', str(error.exception))
        self.assertIn('KnowledgeReaderDeploy', str(error.exception))
        self.assertNotIn('private-aws-payload', str(error.exception))

    def test_successful_install_returns_normally_and_records_release(self):
        for mode in ('google', 'guest', 'cognito'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                output_dir = Path(directory)
                template_path = output_dir / 'cloudformation.json'
                template_path.write_text(json.dumps(aws_deploy.template()))
                checksum = 'a' * 64
                outputs = {'URL': 'https://reader.example.test', 'SettingsSecretArn': 'test-secret',
                           'UserPoolId': 'test-pool', 'UserClientId': 'test-client',
                           'CognitoDomain': 'test-domain', 'StorageBucket': 'test-bucket',
                           'InstanceId': 'test-instance', 'DataVolumeId': 'test-volume',
                           'LogGroup': 'test-log'}
                clients = {name: Mock() for name in ('sts', 'cloudformation', 'secretsmanager', 's3', 'ssm')}
                session = Mock(region_name='ap-south-1')
                session.client.side_effect = clients.__getitem__
                clients['sts'].get_caller_identity.return_value = {'Account': '123456789012'}
                clients['cloudformation'].describe_stacks.return_value = {'Stacks': [
                    {'Tags': [{'Key': 'Project', 'Value': 'KnowledgeReader'}]}]}
                clients['cloudformation'].get_template.return_value = {'TemplateBody': aws_deploy.template()}
                clients['secretsmanager'].get_secret_value.return_value = {'SecretString': '{}'}
                clients['ssm'].describe_instance_information.return_value = {
                    'InstanceInformationList': [{'PingStatus': 'Online'}]}
                clients['ssm'].send_command.return_value = {'Command': {'CommandId': 'test-install'}}
                clients['ssm'].get_command_invocation.return_value = {'Status': 'Success'}
                values = {'PUBLIC_AUTH_MODE': mode, 'OPENAI_API_KEY': 'synthetic-openai',
                          'SUPERMEMORY_API_KEY': 'synthetic-memory',
                          'GOOGLE_CLIENT_ID': 'test.apps.googleusercontent.com',
                          'GOOGLE_CLIENT_SECRET': 'synthetic-google'}
                stdout = io.StringIO()
                with patch('sys.argv', ['aws_deploy', '--deploy', '--output', directory]), \
                        patch.object(aws_deploy, 'dotenv_values', return_value=values), \
                        patch.dict(aws_deploy.os.environ, {}, clear=True), \
                        patch.object(aws_deploy, 'aws_session', return_value=session), \
                        patch.object(aws_deploy, 'package', return_value=(output_dir / 'reader.tar.gz', checksum, template_path)), \
                        patch.object(aws_deploy, 'wait_stack', return_value=outputs), \
                        contextlib.redirect_stdout(stdout):
                    aws_deploy.main()
                self.assertIn('Deployment installed: ' + outputs['URL'], stdout.getvalue())
                self.assertIn('browser-session isolation' if mode == 'guest' else 'sign-in and account isolation',
                              stdout.getvalue())
                record = json.loads((output_dir / 'aws-resources.json').read_text())
                self.assertEqual(record['release'], checksum)
                self.assertEqual(record['ssm_command'], 'test-install')
                for key in ('OPENAI_API_KEY', 'SUPERMEMORY_API_KEY', 'GOOGLE_CLIENT_SECRET'):
                    self.assertNotIn(values[key], stdout.getvalue())
                    self.assertNotIn(values[key], json.dumps(record))


if __name__ == '__main__':
    unittest.main()
