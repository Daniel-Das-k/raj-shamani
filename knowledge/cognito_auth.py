"""Cognito authorization-code flow with PKCE and validated ID tokens."""
import base64
import hashlib
import hmac
import time
from urllib.parse import urlencode

import jwt
import requests


class Cognito:
    def __init__(self, *, region, pool_id, client_id, domain, base_url):
        if not domain.endswith('.amazoncognito.com') or '/' in domain:
            raise ValueError('Use the Cognito user pool domain hostname.')
        self.issuer = f'https://cognito-idp.{region}.amazonaws.com/{pool_id}'
        self.client_id = client_id
        self.domain = 'https://' + domain
        self.callback = base_url + '/auth/callback'
        self.base_url = base_url
        self.keys = jwt.PyJWKClient(self.issuer + '/.well-known/jwks.json', timeout=10)

    def login_url(self, state, verifier, nonce):
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        return self.domain + '/oauth2/authorize?' + urlencode({
            'client_id': self.client_id, 'response_type': 'code', 'scope': 'openid email',
            'redirect_uri': self.callback, 'state': state, 'nonce': nonce,
            'code_challenge_method': 'S256', 'code_challenge': challenge})

    def exchange(self, code, verifier, nonce):
        response = requests.post(self.domain + '/oauth2/token', data={
            'grant_type': 'authorization_code', 'client_id': self.client_id,
            'code': code, 'code_verifier': verifier, 'redirect_uri': self.callback}, timeout=(5, 15))
        response.raise_for_status()
        token = response.json()['id_token']
        claims = jwt.decode(token, self.keys.get_signing_key_from_jwt(token).key,
                            algorithms=['RS256'], audience=self.client_id, issuer=self.issuer,
                            options={'require': ['exp', 'iat', 'sub', 'nonce', 'aud', 'iss']})
        if (claims.get('token_use') != 'id' or claims.get('email_verified') is not True or
                not isinstance(claims.get('nonce'), str) or not hmac.compare_digest(claims['nonce'], nonce) or
                not isinstance(claims['sub'], str) or not claims['sub'] or not isinstance(claims.get('email'), str)):
            raise ValueError('The sign-in response could not be verified.')
        return {'owner_id': claims['sub'], 'email': claims['email'],
                'seconds': max(1, min(3600, int(claims['exp'] - time.time())))}

    def logout_url(self):
        return self.domain + '/logout?' + urlencode({'client_id': self.client_id,
                                                     'logout_uri': self.base_url + '/signed-out'})
