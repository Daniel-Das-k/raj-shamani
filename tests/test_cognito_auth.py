from types import SimpleNamespace
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt

from knowledge.cognito_auth import Cognito


class CognitoTests(unittest.TestCase):
    def setUp(self):
        self.auth = Cognito(region='ap-south-1', pool_id='ap-south-1_test', client_id='client',
                            domain='test.auth.ap-south-1.amazoncognito.com', base_url='https://reader.example.test')
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.auth.keys = Mock()
        self.auth.keys.get_signing_key_from_jwt.return_value = SimpleNamespace(key=self.key.public_key())

    def test_login_uses_code_pkce_nonce_and_exact_callback(self):
        query = parse_qs(urlsplit(self.auth.login_url('state', 'verifier', 'nonce')).query)
        self.assertEqual(query['response_type'], ['code'])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertNotEqual(query['code_challenge'], ['verifier'])
        self.assertEqual(query['nonce'], ['nonce'])
        self.assertEqual(query['redirect_uri'], ['https://reader.example.test/auth/callback'])

    def exchange(self, **changes):
        claims = {'iss': self.auth.issuer, 'aud': 'client', 'sub': 'alice', 'nonce': 'nonce',
                  'exp': int(time.time()) + 3600, 'iat': int(time.time()), 'token_use': 'id',
                  'email': 'alice@example.test', 'email_verified': True, **changes}
        response = Mock()
        response.json.return_value = {'id_token': jwt.encode(claims, self.key, algorithm='RS256')}
        with patch('knowledge.cognito_auth.requests.post', return_value=response) as post:
            result = self.auth.exchange('code', 'verifier', 'nonce')
            self.assertEqual(post.call_args.kwargs['data']['code_verifier'], 'verifier')
            return result

    def test_valid_identity_is_verified_and_tokens_are_not_returned_for_storage(self):
        result = self.exchange()
        self.assertEqual(result['owner_id'], 'alice')
        self.assertEqual(set(result), {'owner_id', 'email', 'seconds'})

    def test_wrong_audience_issuer_nonce_type_unverified_email_and_expiry_fail(self):
        for changes in [{'aud': 'other-client'}, {'iss': 'https://attacker.test'}, {'nonce': 'wrong'},
                        {'email_verified': False}, {'email_verified': 'true'}, {'token_use': 'access'},
                        {'exp': int(time.time()) - 60}]:
            with self.subTest(changes=changes), self.assertRaises((jwt.PyJWTError, ValueError)):
                self.exchange(**changes)
