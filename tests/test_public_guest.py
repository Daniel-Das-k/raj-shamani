from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from starlette.testclient import TestClient

from knowledge.accounts import Accounts, GUEST_SESSION_SECONDS, UsageLimit
from knowledge.public_server import create_app, GUEST_COOKIE, SESSION_COOKIE

BASE = 'https://reader.example.test'
SECRET = 'synthetic-origin-secret-32-characters'


class GuestServerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        self.answer = Mock(return_value={'status': 'insufficient_evidence', 'points': [],
            'recommendations': [], 'message': 'No matching archive evidence.'})
        def library():
            return SimpleNamespace(store=object(), llm=SimpleNamespace(model_name='fixture'),
                answer=self.answer, ready_videos=lambda: [{'id': 'Y566_T-YlNQ'}], close=lambda: None)
        self.config = {'DATA_DIR': str(self.data), 'PUBLIC_BASE_URL': BASE, 'ORIGIN_SECRET': SECRET,
                       'PUBLIC_AUTH_MODE': 'guest', 'QUESTIONS_PER_USER_DAY': '2', 'QUESTIONS_PER_DAY': '5'}
        with patch('knowledge.public_server.Cognito') as identity:
            self.app = create_app(self.config, library_factory=library)
            identity.assert_not_called()
        self.client = self.new_client()

    def new_client(self, address='203.0.113.10'):
        context = TestClient(self.app, base_url=BASE,
            headers={'X-Reader-Origin': SECRET, 'X-Forwarded-For': address}, follow_redirects=False)
        client = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        return client

    def bootstrap(self, client=None):
        client = client or self.client
        response = client.get('/api/account')
        self.assertEqual(response.status_code, 200)
        current = response.json()
        client.headers.update({'X-Account-ID': current['id'], 'X-CSRF-Token': current['csrf'], 'Origin': BASE})
        return current

    def test_home_opens_without_login_and_sets_secure_persistent_cookie(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-accounts="guest"', response.text)
        for flag in ['Secure', 'HttpOnly', 'SameSite=lax', 'Path=/', f'Max-Age={GUEST_SESSION_SECONDS}']:
            self.assertIn(flag, response.headers['set-cookie'])
        current = self.bootstrap()
        self.assertEqual(current['mode'], 'guest')
        self.assertEqual(current['email'], '')
        self.assertEqual(self.bootstrap()['id'], current['id'])
        self.assertNotIn('set-cookie', self.client.get('/').headers)
        for path in ['/auth/login', '/auth/callback?code=old', '/signed-out']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers['location'], '/')

    def test_guests_cannot_read_other_guests_exact_history_or_collections(self):
        alice = self.bootstrap()
        result = self.client.post('/api/ask', json={'question': 'Private guest question'})
        self.assertEqual(result.status_code, 200)
        record = result.json()['record_id']
        body = {'revision': 0, 'items': [{'id': 'private', 'name': 'Private saves', 'items': []}]}
        self.assertEqual(self.client.put('/api/collections', json=body).status_code, 200)
        bob = self.new_client()
        self.assertNotEqual(self.bootstrap(bob)['id'], alice['id'])
        self.assertEqual(bob.get('/api/responses/' + record).status_code, 404)
        self.assertEqual(bob.get('/api/responses').json()['total'], 0)
        self.assertNotIn('Private saves', bob.get('/api/collections').text)
        self.assertEqual(self.client.get('/api/responses/' + record).status_code, 200)
        self.assertEqual(self.client.get('/api/collections').json()['revision'], 1)

    def test_guest_csrf_owner_binding_and_origin_boundary_remain_enforced(self):
        self.assertEqual(self.client.post('/api/ask', json={'question': 'test'}).status_code, 401)
        self.bootstrap()
        for headers, code in [({'Origin': 'https://attacker.test'}, 403), ({'X-CSRF-Token': ''}, 403),
                              ({'X-Account-ID': 'another-browser'}, 409), ({'X-Reader-Origin': ''}, 403)]:
            self.assertEqual(self.client.post('/api/ask', headers=headers, json={'question': 'test'}).status_code, code)
        self.answer.assert_not_called()

    def test_clearing_cookies_and_forging_forwarded_prefix_cannot_reset_daily_limit(self):
        self.bootstrap()
        for _ in range(2):
            self.assertEqual(self.client.post('/api/ask', json={'question': 'test'}).status_code, 200)
        self.client.cookies.clear()
        self.client.headers['X-Forwarded-For'] = '192.0.2.123, 203.0.113.10'
        replacement = self.bootstrap()
        self.assertEqual(self.client.post('/api/ask', json={'question': 'test'}).status_code, 429)
        self.assertEqual(self.answer.call_count, 2)
        with self.app.state.accounts.connect() as db:
            self.assertIsNone(db.execute('SELECT * FROM usage WHERE owner_id=?', (replacement['id'],)).fetchone())
            keys = [row['owner_id'] for row in db.execute('SELECT owner_id FROM usage')]
        self.assertNotIn('203.0.113.10', ' '.join(keys))
        other_network = self.new_client('203.0.113.11')
        self.bootstrap(other_network)
        self.assertEqual(other_network.post('/api/ask', json={'question': 'test'}).status_code, 200)

    def test_expired_forged_or_cognito_sessions_do_not_recover_previous_history(self):
        authenticated = self.app.state.accounts.create_session('alice', 'alice@example.test')
        self.client.cookies.set(SESSION_COOKIE, authenticated)
        self.client.cookies.set(GUEST_COOKIE, authenticated)
        first = self.bootstrap()
        self.assertTrue(first['id'].startswith('guest-'))
        token = self.client.cookies.get(GUEST_COOKIE, domain='reader.example.test', path='/')
        self.app.state.accounts.logout(token)
        second = self.bootstrap()
        self.assertNotEqual(second['id'], first['id'])
        self.assertNotEqual(second['id'], 'alice')

    def test_new_session_creation_is_rate_limited_but_existing_sessions_still_work(self):
        for _ in range(10):
            self.client.cookies.clear()
            self.bootstrap()
        self.assertEqual(self.client.get('/').status_code, 200)
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/').status_code, 429)
        self.assertEqual(self.client.get('/api/account').status_code, 429)


class GuestStorageTests(unittest.TestCase):
    def test_guest_expiry_is_30_days_and_authenticated_expiry_is_still_capped(self):
        with tempfile.TemporaryDirectory() as directory:
            accounts = Accounts(Path(directory) / 'accounts.sqlite3')
            with patch('knowledge.accounts.time.time', return_value=100):
                guest = accounts.create_guest_session()
                authenticated = accounts.create_session('alice', 'alice@example.test', 99999999)
                self.assertEqual(accounts.session(guest)['expires'], 100 + GUEST_SESSION_SECONDS)
                self.assertEqual(accounts.session(authenticated)['expires'], 3700)
            with patch('knowledge.accounts.time.time', return_value=101 + GUEST_SESSION_SECONDS):
                self.assertIsNone(accounts.session(guest))

    def test_shared_network_limit_is_atomic_and_persists_across_store_instances(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'accounts.sqlite3'
            Accounts(path).reserve_question('first-browser', 1, 5, network_id='hashed-network')
            with self.assertRaises(UsageLimit):
                Accounts(path).reserve_question('new-browser', 1, 5, network_id='hashed-network')


if __name__ == '__main__':
    unittest.main()
