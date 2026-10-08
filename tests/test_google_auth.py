from types import SimpleNamespace
import hashlib
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt

from knowledge.google_auth import Google


class GoogleAuthTests(unittest.TestCase):
    def setUp(self):
        self.auth = Google(client_id='test.apps.googleusercontent.com', client_secret='synthetic-secret',
                           base_url='https://reader.example.test')
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.auth.keys = Mock()
        self.auth.keys.get_signing_key_from_jwt.return_value = SimpleNamespace(key=self.key.public_key())

    def exchange(self, changes=None, *, signing_key=None, missing=()):
        claims = {'iss': 'https://accounts.google.com', 'aud': self.auth.client_id,
                  'sub': 'google-subject-alice', 'nonce': 'nonce', 'email': 'alice@example.test',
                  'email_verified': True, 'iat': int(time.time()), 'exp': int(time.time()) + 3600}
        claims.update(changes or {})
        for field in missing:
            claims.pop(field)
        response = Mock()
        response.json.return_value = {'id_token': jwt.encode(claims, signing_key or self.key, algorithm='RS256'),
                                      'access_token': 'not-stored', 'refresh_token': 'not-stored'}
        with patch('knowledge.google_auth.requests.post', return_value=response) as post:
            result = self.auth.exchange('code', 'verifier', 'nonce')
            self.assertEqual(post.call_args.args, ('https://oauth2.googleapis.com/token',))
            self.assertEqual(post.call_args.kwargs['data']['client_secret'], 'synthetic-secret')
            self.assertEqual(post.call_args.kwargs['data']['code_verifier'], 'verifier')
            self.assertFalse(post.call_args.kwargs['allow_redirects'])
            return result

    def test_redirect_is_direct_to_google_with_minimal_scopes_and_pkce(self):
        target = self.auth.login_url('state', 'verifier', 'nonce')
        query = parse_qs(urlsplit(target).query)
        self.assertEqual(urlsplit(target).hostname, 'accounts.google.com')
        self.assertEqual(query['scope'], ['openid email'])
        self.assertEqual(query['prompt'], ['select_account'])
        self.assertEqual(query['redirect_uri'], ['https://reader.example.test/auth/callback'])
        self.assertEqual(query['state'], ['state'])
        self.assertEqual(query['nonce'], ['nonce'])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertNotEqual(query['code_challenge'], ['verifier'])
        self.assertNotIn('synthetic-secret', target)
        self.assertEqual(query['access_type'], ['online'])

    def test_identity_is_stable_when_email_changes_but_not_when_google_account_changes(self):
        original = self.exchange()
        self.assertEqual(original['owner_id'], 'google-' + hashlib.sha256(b'google-subject-alice').hexdigest())
        self.assertEqual(set(original), {'owner_id', 'email', 'seconds'})
        self.assertEqual(original['owner_id'], self.exchange({'email': 'changed@example.test'})['owner_id'])
        self.assertNotEqual(original['owner_id'], self.exchange({'sub': 'another-subject'})['owner_id'])
        self.assertEqual(original['owner_id'], self.exchange({'iss': 'accounts.google.com'})['owner_id'])
        self.assertTrue(1 <= original['seconds'] <= 3600)

    def test_invalid_signed_claims_are_rejected(self):
        for changes in [{'iss': 'https://attacker.test'}, {'aud': 'other-client'},
                        {'aud': [self.auth.client_id, 'another-client']}, {'azp': 'another-client'},
                        {'nonce': 'wrong'}, {'nonce': None}, {'email_verified': False},
                        {'email_verified': 'true'}, {'email': ''}, {'sub': ''}, {'sub': 'a' * 256},
                        {'sub': '\N{SNOWMAN}'}, {'exp': int(time.time()) - 10}, {'iat': int(time.time()) + 60}]:
            with self.subTest(changes=changes), self.assertRaises((jwt.PyJWTError, ValueError)):
                self.exchange(changes)
        for field in ['exp', 'iat', 'nonce', 'sub', 'aud', 'iss', 'email', 'email_verified']:
            with self.subTest(missing=field), self.assertRaises(jwt.PyJWTError):
                self.exchange(missing=[field])

    def test_wrong_signature_is_rejected(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with self.assertRaises(jwt.InvalidSignatureError):
            self.exchange(signing_key=key)

    def test_missing_configuration_fails_without_exposing_values(self):
        for client, secret in [('', ''), ('wrong-private-value', 'secret'), ('test.apps.googleusercontent.com', '')]:
            with self.assertRaises(ValueError) as error:
                Google(client_id=client, client_secret=secret, base_url='https://reader.example.test')
            self.assertNotIn('wrong-private-value', str(error.exception))

    def test_logout_only_leaves_our_application(self):
        self.assertEqual(self.auth.logout_url(), 'https://reader.example.test/signed-out')
