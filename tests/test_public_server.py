from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from starlette.testclient import TestClient

from knowledge.public_server import create_app, SESSION_COOKIE, LOGIN_COOKIE, GUEST_COOKIE
from knowledge.response_history import ResponseHistory

BASE = 'https://reader.example.test'
SECRET = 'synthetic-origin-secret-32-characters'


class PublicServerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        self.answer = Mock(return_value={'status': 'insufficient_evidence', 'points': [],
                                         'recommendations': [], 'message': 'No matching archive evidence.'})
        self.identity = Mock()
        self.identity.login_url.return_value = 'https://example.auth.ap-south-1.amazoncognito.com/oauth2/authorize'
        self.identity.exchange.return_value = {'owner_id': 'alice', 'email': 'alice@example.test', 'seconds': 3600}
        self.identity.logout_url.return_value = 'https://example.auth.ap-south-1.amazoncognito.com/logout'
        def library():
            return SimpleNamespace(store=object(), llm=SimpleNamespace(model_name='fixture'),
                answer=self.answer, ready_videos=lambda: [{'id': 'Y566_T-YlNQ'}],
                status=lambda: {'sources': [], 'total': 1}, close=lambda: None)
        self.app = create_app({'DATA_DIR': str(self.data), 'PUBLIC_BASE_URL': BASE, 'ORIGIN_SECRET': SECRET,
            'MAX_CONCURRENT_ANSWERS': '2', 'QUESTIONS_PER_USER_DAY': '3', 'QUESTIONS_PER_DAY': '5'},
            library_factory=library, identity=self.identity)
        self.context = TestClient(self.app, base_url=BASE, headers={'X-Reader-Origin': SECRET}, follow_redirects=False)
        self.client = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)

    def sign_in(self, owner='alice', client=None):
        client = client or self.client
        token = self.app.state.accounts.create_session(owner, owner + '@example.test')
        client.cookies.set(SESSION_COOKIE, token)
        current = self.app.state.accounts.session(token)
        client.headers.update({'X-Account-ID': owner, 'X-CSRF-Token': current['csrf'], 'Origin': BASE})
        return token

    def test_anonymous_and_direct_origin_access_are_blocked(self):
        self.assertEqual(self.client.get('/').status_code, 303)
        self.assertEqual(self.client.get('/api/responses').status_code, 401)
        self.assertEqual(self.client.post('/api/ask', json={'question': 'question'}).status_code, 401)
        self.assertEqual(self.client.get('/api/account', headers={'X-Reader-Origin': 'wrong'}).status_code, 403)
        self.assertEqual(self.client.get('/health/live', headers={'Host': 'attacker.test'}).status_code, 403)
        self.answer.assert_not_called()

    def test_signin_page_is_public_and_has_no_private_reader_content(self):
        home = self.client.get('/')
        self.assertEqual(home.headers['location'], '/sign-in')
        page = self.client.get('/sign-in')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Sign in to Figuring Out.', page.text)
        self.assertNotIn('id="response-history"', page.text)
        self.assertEqual(page.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.get('/sign-in.js').status_code, 200)
        result = self.client.post('/auth/logout')
        self.assertEqual(result.status_code, 401)
        self.assertIn('error', result.json())

    def test_login_returns_to_saved_route_and_ignores_callback_target(self):
        route = '/#answer/' + 'a' * 32
        self.client.get('/auth/login', params={'next': route})
        state, _, _ = self.identity.login_url.call_args.args
        result = self.client.get('/auth/callback', params={'state': state, 'code': 'test', 'next': 'https://attacker.test'})
        self.assertEqual(result.headers['location'], route)
        self.assertEqual(self.client.get('/sign-in', params={'next': '/#saved/history'}).headers['location'], '/#saved/history')

    def test_login_cannot_redirect_to_external_or_unknown_routes(self):
        for target in ['https://attacker.test', '//attacker.test', '/\\attacker.test', '/auth/logout', '/#answer/wrong', '/#saved\n', '/%23saved']:
            with self.subTest(target=target):
                self.client.get('/auth/login', params={'next': target})
                state, _, _ = self.identity.login_url.call_args.args
                result = self.client.get('/auth/callback', params={'state': state, 'code': 'test'})
                self.assertEqual(result.headers['location'], '/')

    def test_guest_cookies_do_not_grant_access_or_move_data_to_an_account(self):
        guest = self.app.state.accounts.create_guest_session()
        owner = self.app.state.accounts.session(guest)['owner_id']
        self.app.state.history.for_owner(owner).save({'id': 'b'*32, 'created_at': '2026-10-08', 'question': 'Guest private question', 'status': 'answered'})
        self.client.cookies.set(GUEST_COOKIE, guest)
        self.client.cookies.set(SESSION_COOKIE, guest)
        self.assertEqual(self.client.get('/api/account').status_code, 401)
        self.assertEqual(self.client.get('/api/responses/' + 'b'*32).status_code, 401)
        self.sign_in('alice')
        self.assertEqual(self.client.get('/api/responses').json()['total'], 0)
        self.assertEqual(self.client.get('/api/responses/' + 'b'*32).status_code, 404)

    def test_login_checks_state_pkce_cookie_and_replay_then_rotates_session(self):
        response = self.client.get('/auth/login')
        state, verifier, nonce = self.identity.login_url.call_args.args
        self.assertIn('Secure', response.headers['set-cookie'])
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        self.assertIn('SameSite=lax', response.headers['set-cookie'])
        self.assertEqual(self.client.get('/auth/callback?state=wrong&code=test').status_code, 400)
        self.identity.exchange.assert_not_called()
        response = self.client.get('/auth/callback', params={'state': state, 'code': 'synthetic-code'})
        self.assertEqual(response.status_code, 303)
        self.identity.exchange.assert_called_once_with('synthetic-code', verifier, nonce)
        self.assertEqual(self.client.get('/api/account').json()['id'], 'alice')
        self.assertEqual(self.client.get('/auth/callback', params={'state': state, 'code': 'synthetic-code'}).status_code, 400)

    def test_csrf_and_account_binding_protect_mutations(self):
        self.sign_in()
        for headers in [{'Origin': 'https://attacker.test'}, {'X-CSRF-Token': ''}, {'X-Account-ID': 'bob'}]:
            response = self.client.post('/api/ask', headers=headers, json={'question': 'test'})
            self.assertIn(response.status_code, [403, 409])
        self.answer.assert_not_called()
        self.assertEqual(self.client.post('/api/ask', json={'question': 'test', 'source_id': []}).status_code, 400)
        mismatch = self.client.get('/api/collections', headers={'X-Account-ID': 'bob'})
        self.assertEqual(mismatch.json()['code'], 'session_changed')

    def test_history_is_owned_even_when_another_user_knows_the_exact_record_id(self):
        self.sign_in()
        response = self.client.post('/api/ask', json={'question': 'Alice private question'})
        self.assertEqual(response.status_code, 200)
        record_id = response.json()['record_id']
        self.assertEqual(self.client.get('/api/responses').json()['total'], 1)
        self.assertEqual(self.client.get('/api/responses/' + record_id).status_code, 200)
        self.sign_in('bob')
        self.assertEqual(self.client.get('/api/responses').json()['total'], 0)
        self.assertEqual(self.client.get('/api/responses/' + record_id).status_code, 404)
        self.assertEqual(ResponseHistory(self.data / 'responses.sqlite3').list()['total'], 0)

    def test_old_unowned_history_is_not_exposed_to_new_accounts(self):
        self.app.state.history.save({'id': 'a'*32, 'created_at': '2026-01-01', 'question': 'Local private question', 'status': 'answered'})
        self.sign_in()
        self.assertEqual(self.client.get('/api/responses').json()['total'], 0)
        self.assertEqual(self.client.get('/api/responses/' + 'a'*32).status_code, 404)

    def test_reopened_answers_match_fresh_answers_without_internal_diagnostic_ids(self):
        self.sign_in()
        self.answer.return_value = {**self.answer.return_value, 'diagnostic_id': 'private-diagnostic'}
        for endpoint in ['/api/ask', '/api/ask/stream']:
            with self.subTest(endpoint=endpoint):
                result = self.client.post(endpoint, json={'question': 'A saved question'})
                self.assertEqual(result.status_code, 200)
                answer = (json.loads(result.text.splitlines()[-1])['response']
                          if endpoint.endswith('/stream') else result.json())
                self.assertNotIn('diagnostic_id', answer)
                record_id = answer['record_id']
                for _ in range(2):
                    saved = self.client.get('/api/responses/' + record_id)
                    self.assertEqual(saved.status_code, 200)
                    self.assertEqual(saved.json()['response'], answer)
                stored = self.app.state.history.for_owner('alice').get(record_id)
                self.assertEqual(stored['response']['diagnostic_id'], 'private-diagnostic')

    def test_account_collections_conflicts_and_logout_are_enforced(self):
        token = self.sign_in()
        self.assertEqual(self.client.get('/api/collections').json()['revision'], 0)
        body = {'revision': 0, 'items': [{'id': 'alice', 'name': 'Private', 'items': []}]}
        self.assertEqual(self.client.put('/api/collections', json=body).status_code, 200)
        self.assertEqual(self.client.put('/api/collections', json=body).status_code, 409)
        self.assertEqual(self.client.post('/auth/logout').status_code, 200)
        self.assertIsNone(self.app.state.accounts.session(token))
        self.assertEqual(self.client.get('/api/collections').status_code, 401)
        self.sign_in('bob')
        self.assertNotIn('Private', self.client.get('/api/collections').text)

    def test_stream_has_only_stage_messages_before_final_and_reserves_daily_usage(self):
        self.sign_in()
        def answer(question, scope, progress):
            progress({'type': 'stage', 'phase': 'review', 'message': 'Checking clips', 'excerpts': ['unverified text']})
            progress({'type': 'stage', 'phase': 'compose', 'message': 'Checking sources', 'excerpts': ['unverified text']})
            progress({'type': 'excerpts', 'excerpts': ['unverified text']})
            return {'status': 'insufficient_evidence', 'points': [], 'message': 'No match'}
        self.answer.side_effect = answer
        response = self.client.post('/api/ask/stream', json={'question': 'Unrelated question'})
        events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        self.assertEqual([e['type'] for e in events], ['stage', 'stage', 'answer'])
        self.assertEqual(events[0], {'type': 'stage', 'phase': 'review', 'message': 'Checking clips'})
        self.assertEqual(events[1], {'type': 'stage', 'phase': 'compose', 'message': 'Checking sources'})
        self.assertIn('record_id', events[-1]['response'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        for _ in range(2):
            self.assertEqual(self.client.post('/api/ask/stream', json={'question': 'test'}).status_code, 200)
        self.assertEqual(self.client.post('/api/ask/stream', json={'question': 'test'}).status_code, 429)
        self.assertEqual(self.answer.call_count, 3)

    def test_two_accounts_can_run_concurrently_but_same_account_cannot_double_submit(self):
        self.sign_in()
        entered, release = threading.Event(), threading.Event()
        def answer(question, scope, progress):
            if question == 'held':
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('Test timed out')
            return {'status': 'insufficient_evidence', 'points': [], 'message': 'No match'}
        self.answer.side_effect = answer
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.client.post, '/api/ask', json={'question': 'held'})
            self.assertTrue(entered.wait(3))
            try:
                self.assertEqual(self.client.post('/api/ask', json={'question': 'duplicate'}).status_code, 429)
                self.sign_in('bob')
                self.assertEqual(self.client.post('/api/ask', json={'question': 'other account'}).status_code, 200)
            finally:
                release.set()
            self.assertEqual(pending.result().status_code, 200)
        self.assertEqual(self.app.state.history.for_owner('alice').list()['total'], 1)
        self.assertEqual(self.app.state.history.for_owner('bob').list()['total'], 1)

    def test_public_html_enables_account_mode_and_request_size_is_bounded(self):
        self.sign_in()
        self.assertIn('data-accounts="required"', self.client.get('/').text)
        self.assertEqual(self.client.post('/api/ask', json={'question': 'a'*33000}).status_code, 413)
        self.assertEqual(self.client.post('/api/search', json={'question': 'test'}).status_code, 404)
        self.assertEqual(self.client.get('/.env').status_code, 404)
        self.assertEqual(self.client.get('/data/responses.sqlite3').status_code, 404)


class HistoryMigrationTests(unittest.TestCase):
    def test_migration_preserves_legacy_rows_without_assigning_them_to_any_user(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.sqlite3'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE responses (id TEXT PRIMARY KEY, created_at TEXT, question TEXT, status TEXT, record TEXT)')
                db.execute('INSERT INTO responses VALUES(?,?,?,?,?)', ('a'*32, '2026', 'private', 'answered', '{}'))
            history = ResponseHistory(path)
            self.assertEqual(history.list()['total'], 1)
            self.assertEqual(history.for_owner('alice').list()['total'], 0)
