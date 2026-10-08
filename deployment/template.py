"""CloudFormation for one bounded public pilot; creates only stack-owned resources."""
import json


def ref(name):
    return {'Ref': name}


def attr(name, key):
    return {'Fn::GetAtt': [name, key]}


def sub(value):
    return {'Fn::Sub': value}


def template():
    resources = {}
    def resource(name, kind, properties, **extra):
        resources[name] = {'Type': kind, 'Properties': properties, **extra}
    tags = [{'Key': 'Project', 'Value': 'KnowledgeReader'}, {'Key': 'Stack', 'Value': ref('AWS::StackName')}]
    resource('Network', 'AWS::EC2::VPC', {'CidrBlock': '10.42.0.0/24', 'EnableDnsSupport': True,
                                         'EnableDnsHostnames': True, 'Tags': tags})
    resource('Gateway', 'AWS::EC2::InternetGateway', {'Tags': tags})
    resource('GatewayAttachment', 'AWS::EC2::VPCGatewayAttachment', {'VpcId': ref('Network'), 'InternetGatewayId': ref('Gateway')})
    resource('Subnet', 'AWS::EC2::Subnet', {'VpcId': ref('Network'), 'CidrBlock': '10.42.0.0/26',
        'AvailabilityZone': {'Fn::Select': [0, {'Fn::GetAZs': ''}]}, 'MapPublicIpOnLaunch': True, 'Tags': tags})
    resource('Routes', 'AWS::EC2::RouteTable', {'VpcId': ref('Network'), 'Tags': tags})
    resource('InternetRoute', 'AWS::EC2::Route', {'RouteTableId': ref('Routes'), 'DestinationCidrBlock': '0.0.0.0/0',
                                               'GatewayId': ref('Gateway')}, DependsOn='GatewayAttachment')
    resource('SubnetRoutes', 'AWS::EC2::SubnetRouteTableAssociation', {'RouteTableId': ref('Routes'), 'SubnetId': ref('Subnet')})
    # Public IPv4 is used only for outbound provider/SSM traffic, avoiding a NAT gateway.
    # A VPC CIDR rule does not admit CloudFront origin traffic. AWS requires its
    # managed origin-facing prefix list (or the service-managed origin SG).
    # The app also verifies the distribution hostname and secret origin header.
    resource('AppSecurityGroup', 'AWS::EC2::SecurityGroup', {'GroupDescription': 'Private CloudFront VPC origin only; no SSH',
        'VpcId': ref('Network'), 'SecurityGroupIngress': [{'IpProtocol': 'tcp', 'FromPort': 8000, 'ToPort': 8000,
                                                        'SourcePrefixListId': ref('CloudFrontPrefixListId')}], 'Tags': tags})
    resource('Storage', 'AWS::S3::Bucket', {
        'BucketName': sub('${AWS::StackName}-storage-${AWS::AccountId}'),
        'PublicAccessBlockConfiguration': {'BlockPublicAcls': True, 'IgnorePublicAcls': True,
                                          'BlockPublicPolicy': True, 'RestrictPublicBuckets': True},
        'BucketEncryption': {'ServerSideEncryptionConfiguration': [{'ServerSideEncryptionByDefault': {'SSEAlgorithm': 'AES256'}}]},
        'VersioningConfiguration': {'Status': 'Enabled'},
        'LifecycleConfiguration': {'Rules': [
            {'Id': 'BackupRetention', 'Status': 'Enabled', 'Prefix': 'backups/', 'ExpirationInDays': 35,
             'NoncurrentVersionExpiration': {'NoncurrentDays': 7}},
            {'Id': 'OldReleaseVersions', 'Status': 'Enabled', 'Prefix': 'releases/',
             'NoncurrentVersionExpiration': {'NoncurrentDays': 30}, 'AbortIncompleteMultipartUpload': {'DaysAfterInitiation': 1}}]},
        'Tags': tags}, DeletionPolicy='Retain', UpdateReplacePolicy='Retain')
    resource('StoragePolicy', 'AWS::S3::BucketPolicy', {'Bucket': ref('Storage'), 'PolicyDocument': {
        'Version': '2012-10-17', 'Statement': [{'Sid': 'RequireTLS', 'Effect': 'Deny', 'Principal': '*', 'Action': 's3:*',
            'Resource': [attr('Storage', 'Arn'), sub('${Storage.Arn}/*')],
            'Condition': {'Bool': {'aws:SecureTransport': 'false'}}}]}})
    resource('Settings', 'AWS::SecretsManager::Secret', {'Name': sub('${AWS::StackName}-Settings-main'),
        'Description': 'Knowledge reader provider keys and runtime configuration',
        'GenerateSecretString': {'SecretStringTemplate': '{}', 'GenerateStringKey': 'ORIGIN_SECRET',
                                 'PasswordLength': 48, 'ExcludePunctuation': True}, 'Tags': tags},
        DeletionPolicy='Retain', UpdateReplacePolicy='Retain')
    resource('RuntimeRole', 'AWS::IAM::Role', {
        'RoleName': sub('${AWS::StackName}-RuntimeRole-main'),
        'AssumeRolePolicyDocument': {'Version': '2012-10-17', 'Statement': [
            {'Effect': 'Allow', 'Principal': {'Service': 'ec2.amazonaws.com'}, 'Action': 'sts:AssumeRole'}]},
        'ManagedPolicyArns': [sub('arn:${AWS::Partition}:iam::aws:policy/AmazonSSMManagedInstanceCore')],
        'Policies': [{'PolicyName': 'ReaderStorageAndSettings', 'PolicyDocument': {'Version': '2012-10-17', 'Statement': [
            {'Effect': 'Allow', 'Action': ['s3:GetObject'], 'Resource': [sub('${Storage.Arn}/releases/*'), sub('${Storage.Arn}/backups/*')]},
            {'Effect': 'Allow', 'Action': ['s3:PutObject'], 'Resource': sub('${Storage.Arn}/backups/*')},
            {'Effect': 'Allow', 'Action': ['secretsmanager:GetSecretValue'], 'Resource': ref('Settings')},
            {'Effect': 'Allow', 'Action': ['cloudwatch:PutMetricData'], 'Resource': '*',
             'Condition': {'StringEquals': {'cloudwatch:namespace': 'KnowledgeReader'}}},
            {'Effect': 'Allow', 'Action': ['logs:CreateLogStream', 'logs:PutLogEvents', 'logs:DescribeLogStreams'],
             'Resource': attr('AppLogs', 'Arn')}]}}], 'Tags': tags})
    resource('RuntimeProfile', 'AWS::IAM::InstanceProfile', {
        'InstanceProfileName': sub('${AWS::StackName}-RuntimeProfile-main'), 'Roles': [ref('RuntimeRole')]})
    resource('AppLogs', 'AWS::Logs::LogGroup', {'LogGroupName': sub('${AWS::StackName}-AppLogs-main'),
        'RetentionInDays': 14, 'Tags': tags}, DeletionPolicy='Retain', UpdateReplacePolicy='Retain')
    resource('DataVolume', 'AWS::EC2::Volume', {'AvailabilityZone': attr('Subnet', 'AvailabilityZone'),
        'Encrypted': True, 'Size': 20, 'VolumeType': 'gp3', 'Tags': tags}, DeletionPolicy='Retain', UpdateReplacePolicy='Retain')
    resource('Instance', 'AWS::EC2::Instance', {
        'ImageId': ref('ImageId'), 'InstanceType': ref('InstanceType'), 'SubnetId': ref('Subnet'),
        'SecurityGroupIds': [ref('AppSecurityGroup')], 'IamInstanceProfile': ref('RuntimeProfile'),
        'MetadataOptions': {'HttpTokens': 'required', 'HttpPutResponseHopLimit': 1},
        'BlockDeviceMappings': [{'DeviceName': '/dev/xvda', 'Ebs': {'Encrypted': True, 'VolumeSize': 12,
                                                                'VolumeType': 'gp3', 'DeleteOnTermination': True}}],
        'UserData': {'Fn::Base64': '#!/bin/bash\nset -eu\nsystemctl enable --now amazon-ssm-agent\n'},
        'Tags': tags}, DependsOn=['InternetRoute', 'SubnetRoutes'])
    resource('DataAttachment', 'AWS::EC2::VolumeAttachment', {'Device': '/dev/sdf', 'InstanceId': ref('Instance'), 'VolumeId': ref('DataVolume')})
    resource('VpcOrigin', 'AWS::CloudFront::VpcOrigin', {'VpcOriginEndpointConfig': {
        'Name': sub('${AWS::StackName}-origin'), 'Arn': sub('arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:instance/${Instance}'),
        'HTTPPort': 8000, 'HTTPSPort': 443, 'OriginProtocolPolicy': 'http-only'}})
    resource('NoCache', 'AWS::CloudFront::CachePolicy', {'CachePolicyConfig': {
        'Name': sub('${AWS::StackName}-${AWS::Region}-no-cache'), 'DefaultTTL': 0, 'MaxTTL': 0, 'MinTTL': 0,
        'ParametersInCacheKeyAndForwardedToOrigin': {'EnableAcceptEncodingGzip': False,
            'CookiesConfig': {'CookieBehavior': 'none'}, 'HeadersConfig': {'HeaderBehavior': 'none'},
            'QueryStringsConfig': {'QueryStringBehavior': 'none'}}}})
    resource('ForwardRequests', 'AWS::CloudFront::OriginRequestPolicy', {'OriginRequestPolicyConfig': {
        'Name': sub('${AWS::StackName}-${AWS::Region}-requests'), 'CookiesConfig': {'CookieBehavior': 'all'},
        'HeadersConfig': {'HeaderBehavior': 'allViewer'}, 'QueryStringsConfig': {'QueryStringBehavior': 'all'}}})
    resource('Distribution', 'AWS::CloudFront::Distribution', {'DistributionConfig': {
        'Enabled': True, 'Comment': sub('${AWS::StackName} authenticated reader'), 'HttpVersion': 'http2and3',
        'PriceClass': 'PriceClass_200', 'ViewerCertificate': {'CloudFrontDefaultCertificate': True},
        'Origins': [{'Id': 'Reader', 'DomainName': attr('Instance', 'PrivateDnsName'),
                     'VpcOriginConfig': {'VpcOriginId': attr('VpcOrigin', 'Id'), 'OriginReadTimeout': 60, 'OriginKeepaliveTimeout': 5},
                     'OriginCustomHeaders': [{'HeaderName': 'X-Reader-Origin',
                       'HeaderValue': sub('{{resolve:secretsmanager:${Settings}:SecretString:ORIGIN_SECRET}}')}]}],
        'DefaultCacheBehavior': {'TargetOriginId': 'Reader', 'ViewerProtocolPolicy': 'redirect-to-https',
            'AllowedMethods': ['GET', 'HEAD', 'OPTIONS', 'PUT', 'POST', 'PATCH', 'DELETE'], 'CachedMethods': ['GET', 'HEAD'],
            'CachePolicyId': ref('NoCache'), 'OriginRequestPolicyId': ref('ForwardRequests')},
        'CustomErrorResponses': [{'ErrorCode': code, 'ErrorCachingMinTTL': 0} for code in (400, 403, 404, 500, 502, 503, 504)]},
        'Tags': tags})
    resource('Users', 'AWS::Cognito::UserPool', {'UserPoolName': sub('${AWS::StackName}-users'), 'UserPoolTier': 'LITE',
        'DeletionProtection': 'ACTIVE', 'UsernameAttributes': ['email'], 'AutoVerifiedAttributes': ['email'],
        'UsernameConfiguration': {'CaseSensitive': False}, 'AdminCreateUserConfig': {'AllowAdminCreateUserOnly': False},
        'AccountRecoverySetting': {'RecoveryMechanisms': [{'Name': 'verified_email', 'Priority': 1}]},
        'Policies': {'PasswordPolicy': {'MinimumLength': 12, 'RequireLowercase': True, 'RequireUppercase': True,
                                        'RequireNumbers': True, 'RequireSymbols': True}},
        'Schema': [{'Name': 'email', 'AttributeDataType': 'String', 'Required': True, 'Mutable': True}],
        'UserPoolTags': {'Project': 'KnowledgeReader'}}, DeletionPolicy='Retain', UpdateReplacePolicy='Retain')
    resource('UserClient', 'AWS::Cognito::UserPoolClient', {
        'UserPoolId': ref('Users'), 'ClientName': 'Reader', 'GenerateSecret': False,
        'AllowedOAuthFlowsUserPoolClient': True, 'AllowedOAuthFlows': ['code'], 'AllowedOAuthScopes': ['openid', 'email'],
        'SupportedIdentityProviders': ['COGNITO'], 'PreventUserExistenceErrors': 'ENABLED', 'EnableTokenRevocation': True,
        'ExplicitAuthFlows': ['ALLOW_REFRESH_TOKEN_AUTH'], 'IdTokenValidity': 60, 'AccessTokenValidity': 60,
        'RefreshTokenValidity': 1, 'TokenValidityUnits': {'IdToken': 'minutes', 'AccessToken': 'minutes', 'RefreshToken': 'days'},
        'CallbackURLs': [sub('https://${Distribution.DomainName}/auth/callback')],
        'LogoutURLs': [sub('https://${Distribution.DomainName}/signed-out')]})
    resource('UserDomain', 'AWS::Cognito::UserPoolDomain', {'UserPoolId': ref('Users'), 'ManagedLoginVersion': 1,
        'Domain': sub('${AWS::StackName}-${AWS::AccountId}-${AWS::Region}')})
    resource('InstanceAlarm', 'AWS::CloudWatch::Alarm', {'AlarmName': sub('${AWS::StackName}-InstanceAlarm'),
        'AlarmDescription': 'Reader instance status check failed',
        'Namespace': 'AWS/EC2', 'MetricName': 'StatusCheckFailed', 'Dimensions': [{'Name': 'InstanceId', 'Value': ref('Instance')}],
        'Statistic': 'Maximum', 'Period': 60, 'EvaluationPeriods': 2, 'Threshold': 1,
        'ComparisonOperator': 'GreaterThanOrEqualToThreshold', 'TreatMissingData': 'breaching'})
    resource('BackupAlarm', 'AWS::CloudWatch::Alarm', {'AlarmName': sub('${AWS::StackName}-BackupAlarm'),
        'AlarmDescription': 'No successful reader backup in the last 48 hours',
        'Namespace': 'KnowledgeReader', 'MetricName': 'BackupSucceeded',
        'Dimensions': [{'Name': 'BackupBucket', 'Value': ref('Storage')}], 'Statistic': 'Sum',
        'Period': 86400, 'EvaluationPeriods': 2, 'Threshold': 1, 'ComparisonOperator': 'LessThanThreshold', 'TreatMissingData': 'breaching'})
    return {'AWSTemplateFormatVersion': '2010-09-09', 'Description': 'Public reader: Cognito, CloudFront VPC origin, EC2, retained encrypted data and S3 backups.',
        'Parameters': {
            'CloudFrontPrefixListId': {'Type': 'String', 'AllowedPattern': 'pl-[a-f0-9]+',
                'Description': 'AWS-managed com.amazonaws.global.cloudfront.origin-facing prefix list in this region'},
            'ImageId': {'Type': 'AWS::SSM::Parameter::Value<AWS::EC2::Image::Id>',
                        'Default': '/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64'},
            'InstanceType': {'Type': 'String', 'Default': 't3.small', 'AllowedValues': ['t3.small', 't3.medium']}},
        'Resources': resources, 'Outputs': {
            'URL': {'Value': sub('https://${Distribution.DomainName}')}, 'InstanceId': {'Value': ref('Instance')},
            'DataVolumeId': {'Value': ref('DataVolume')}, 'StorageBucket': {'Value': ref('Storage')},
            'SettingsSecretArn': {'Value': ref('Settings')}, 'LogGroup': {'Value': ref('AppLogs')},
            'UserPoolId': {'Value': ref('Users')}, 'UserClientId': {'Value': ref('UserClient')},
            'CognitoDomain': {'Value': sub('${UserDomain}.auth.${AWS::Region}.amazoncognito.com')},
            'DistributionId': {'Value': ref('Distribution')}}}


if __name__ == '__main__':
    print(json.dumps(template(), indent=2))
