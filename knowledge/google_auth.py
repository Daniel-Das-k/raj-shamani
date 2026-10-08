"""Google OpenID Connect code flow; credentials and tokens stay on the server."""
import base64
import hashlib
import hmac
import time
from urllib.parse import urlencode

import jwt
import requests


class Google:
    def __init__(self, *, client_id, client_secret, base_url):
        if not client_id or not client_id.endswith('.apps.googleusercontent.com') or not client_secret:
            raise ValueError('Configure GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET for a Google web application.')
        self.client_id, self.client_secret = client_id, client_secret
        self.base_url = base_url
        self.callback = base_url + '/auth/callback'
        self.keys = jwt.PyJWKClient('https://www.googleapis.com/oauth2/v3/certs', timeout=10)

    def login_url(self, state, verifier, nonce):
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        return 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
            'client_id': self.client_id, 'response_type': 'code', 'scope': 'openid email',
            'redirect_uri': self.callback, 'state': state, 'nonce': nonce,
            'code_challenge_method': 'S256', 'code_challenge': challenge,
            'prompt': 'select_account', 'access_type': 'online'})

    def exchange(self, code, verifier, nonce):
        response = requests.post('https://oauth2.googleapis.com/token', data={
            'grant_type': 'authorization_code', 'client_id': self.client_id,
            'client_secret': self.client_secret, 'code': code, 'code_verifier': verifier,
            'redirect_uri': self.callback}, timeout=(5, 15), allow_redirects=False)
        response.raise_for_status()
        token = response.json()['id_token']
        claims = jwt.decode(token, self.keys.get_signing_key_from_jwt(token).key,
                            algorithms=['RS256'], audience=self.client_id,
                            issuer=['https://accounts.google.com', 'accounts.google.com'],
                            options={'require': ['exp', 'iat', 'sub', 'nonce', 'aud', 'iss', 'email', 'email_verified'],
                                     'strict_aud': True})
        subject, email = claims['sub'], claims['email']
        if (claims['email_verified'] is not True or
                not isinstance(claims['nonce'], str) or not hmac.compare_digest(claims['nonce'], nonce) or
                claims.get('azp', self.client_id) != self.client_id or
                not isinstance(subject, str) or not 1 <= len(subject) <= 255 or not subject.isascii() or
                not isinstance(email, str) or not email or len(email) > 320):
            raise ValueError('The Google sign-in response could not be verified.')
        # Stable Google subject, never email; namespace prevents linking another provider's account.
        owner = 'google-' + hashlib.sha256(subject.encode('ascii')).hexdigest()
        return {'owner_id': owner, 'email': email,
                'seconds': max(1, min(3600, int(claims['exp'] - time.time())))}

    def logout_url(self):
        # End this application's session, without signing out the user's Google account.
        return self.base_url + '/signed-out'
