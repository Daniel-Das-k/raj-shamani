import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
from starlette.testclient import TestClient
from knowledge.public_server import create_app, LOGIN_COOKIE, SESSION_COOKIE

BASE = 'https://reader.example.test'
SECRET = 'synthetic-origin-secret-32-characters'


class PublicGoogleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.identity = Mock()
        self.identity.login_url.return_value = 'https://accounts.google.com/o/oauth2/v2/auth'
        self.identity.logout_url.return_value = BASE + '/signed-out'
        self.identity.exchange.side_effect = lambda code, verifier, nonce: {
            'owner_id': 'google-' + code, 'email': code + '@example.test', 'seconds': 3600}
        answer = Mock(return_value={'status': 'insufficient_evidence', 'points': [],
                                   'recommendations': [], 'message': 'No matching evidence.'})
        library = lambda: SimpleNamespace(store=object(), llm=SimpleNamespace(model_name='fixture'),
            answer=answer, ready_videos=lambda: [{'id': 'Y566_T-YlNQ'}], close=lambda: None)
        self.app = create_app({'PUBLIC_AUTH_MODE': 'google', 'DATA_DIR': temporary.name,
            'PUBLIC_BASE_URL': BASE, 'ORIGIN_SECRET': SECRET}, library_factory=library, identity=self.identity)
        context = TestClient(self.app, base_url=BASE, headers={'X-Reader-Origin': SECRET}, follow_redirects=False)
        self.client = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def start(self, target='/#saved/history'):
        response = self.client.get('/auth/login', params={'next': target})
        self.assertEqual(response.headers['location'], self.identity.login_url.return_value)
        return self.identity.login_url.call_args.args[0]

    def signin(self, user='alice'):
        state = self.start()
        response = self.client.get('/auth/callback', params={'state': state, 'code': user})
        self.assertEqual(response.headers['location'], '/#saved/history')
        current = self.client.get('/api/account').json()
        self.client.headers.update({'X-Account-ID': current['id'], 'X-CSRF-Token': current['csrf'], 'Origin': BASE})
        return response

    def test_signup_and_signin_are_branded_public_pages_and_keep_destination(self):
        for path, title in [('/sign-in', 'Sign in.'), ('/sign-up', 'Create an account.')]:
            response = self.client.get(path, params={'next': '/#saved/history'})
            self.assertEqual(response.status_code, 200)
            self.assertIn(title, response.text)
            self.assertIn('Continue with Google', response.text)
            self.assertNotIn('password', response.text)
            self.assertIn('next=%2F%23saved%2Fhistory', response.text)
            self.assertNotIn('id="response-history"', response.text)
        self.signin()
        for path in ['/sign-in', '/sign-up']:
            response = self.client.get(path, params={'next': '/#conversations'})
            self.assertEqual(response.headers['location'], '/#conversations')

    def test_cancelled_consent_is_retryable_and_keeps_route_without_reflecting_provider_text(self):
        state = self.start()
        result = self.client.get('/auth/callback', params={'state': state, 'error': 'access_denied', 'error_description': '<script>private</script>'})
        self.identity.exchange.assert_not_called()
        self.assertEqual(result.status_code, 303)
        query = parse_qs(urlsplit(result.headers['location']).query)
        self.assertEqual(query, {'next': ['/#saved/history'], 'error': ['cancelled']})
        self.assertNotIn(LOGIN_COOKIE, self.client.cookies)
        page = self.client.get(result.headers['location'])
        self.assertIn('Sign-in was cancelled.', page.text)
        self.assertNotIn('<script>private</script>', page.text)
        self.assertEqual(self.client.get('/api/account').status_code, 401)
        self.signin()

    def test_failed_exchange_issues_no_session_and_allows_retry(self):
        state = self.start()
        self.identity.exchange.side_effect = ValueError('sensitive-provider-error')
        result = self.client.get('/auth/callback', params={'state': state, 'code': 'failed'})
        self.assertEqual(result.status_code, 303)
        self.assertNotIn('sensitive-provider-error', result.headers['location'])
        self.assertNotIn(SESSION_COOKIE, self.client.cookies)
        self.assertIn('Sign-in could not finish.', self.client.get(result.headers['location']).text)

    def test_new_and_returning_google_accounts_only_see_their_own_history_and_collections(self):
        self.signin('alice')
        record = self.client.post('/api/ask', json={'question': 'Alice private question'}).json()['record_id']
        collection = {'revision': 0, 'items': [{'id': 'alice', 'name': 'Alice private saves', 'items': []}]}
        self.assertEqual(self.client.put('/api/collections', json=collection).status_code, 200)
        logout = self.client.post('/auth/logout')
        self.assertEqual(logout.json()['redirect'], BASE + '/signed-out')
        self.assertEqual(self.client.get('/api/responses/' + record).status_code, 401)
        self.signin('bob')
        self.assertEqual(self.client.get('/api/responses/' + record).status_code, 404)
        self.assertEqual(self.client.get('/api/responses').json()['total'], 0)
        self.assertNotIn('Alice private saves', self.client.get('/api/collections').text)
        self.signin('alice')
        self.assertEqual(self.client.get('/api/responses/' + record).status_code, 200)
        self.assertIn('Alice private saves', self.client.get('/api/collections').text)

    def test_legacy_provider_session_cannot_be_treated_as_a_google_account(self):
        token = self.app.state.accounts.create_session('legacy-cognito-user', 'alice@example.test')
        self.client.cookies.set(SESSION_COOKIE, token)
        self.assertEqual(self.client.get('/api/account').status_code, 401)
        self.assertEqual(self.client.get('/').headers['location'], '/sign-in')
