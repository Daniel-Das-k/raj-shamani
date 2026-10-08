from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from knowledge.accounts import Accounts, CollectionConflict, UsageLimit


class AccountTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'accounts.sqlite3'
        self.accounts = Accounts(self.path)

    def test_sessions_are_hashed_persistent_expiring_and_revocable(self):
        with patch('knowledge.accounts.time.time', return_value=100):
            token = self.accounts.create_session('alice', 'alice@example.test', 60)
            self.assertEqual(Accounts(self.path).session(token)['owner_id'], 'alice')
        self.assertNotIn(token.encode(), self.path.read_bytes())
        with patch('knowledge.accounts.time.time', return_value=161):
            self.assertIsNone(self.accounts.session(token))
        token = self.accounts.create_session('bob', 'bob@example.test')
        self.accounts.logout(token)
        self.assertIsNone(self.accounts.session(token))

    def test_login_attempt_is_bound_to_state_expires_and_is_single_use(self):
        with patch('knowledge.accounts.time.time', return_value=100):
            state, verifier, nonce = self.accounts.begin_login()
            self.assertIsNone(self.accounts.consume_login('wrong-state'))
            self.assertEqual(self.accounts.consume_login(state)['verifier'], verifier)
            self.assertIsNone(self.accounts.consume_login(state))
            state, _, _ = self.accounts.begin_login()
        with patch('knowledge.accounts.time.time', return_value=701):
            self.assertIsNone(self.accounts.consume_login(state))

    def test_collections_are_isolated_and_stale_updates_cannot_overwrite(self):
        items = [{'id': 'a', 'name': 'Private ideas', 'items': [
            {'id': 'Y566_T-YlNQ', 'title': 'Conversation', 'kind': 'episode'}]}]
        result = self.accounts.save_collections('alice', 0, items)
        self.assertEqual(result['revision'], 1)
        self.assertEqual(Accounts(self.path).collections('alice')['items'], items)
        self.assertNotIn('Private ideas', json.dumps(self.accounts.collections('bob')))
        with self.assertRaises(CollectionConflict):
            self.accounts.save_collections('alice', 0, [])
        self.assertEqual(self.accounts.collections('alice')['items'], items)
        self.accounts.save_collections('bob', 0, [])
        self.assertEqual(self.accounts.collections('alice')['revision'], 1)

    def test_invalid_collection_timestamps_and_ids_are_rejected(self):
        for item in [None, {'id': '../private'}, {'id': 'Y566_T-YlNQ', 'title': 'a', 'kind': 'moment',
                     'quote': 'text', 'start': float('nan'), 'end': 10}]:
            with self.subTest(item=item), self.assertRaises(ValueError):
                self.accounts.save_collections('alice', 0, [{'id': 'a', 'name': 'a', 'items': [item]}])
        self.assertEqual(self.accounts.collections('alice')['revision'], 0)

    def test_saved_clip_preserves_readable_title_summary_and_exact_bounds(self):
        item = {'id': 'Y566_T-YlNQ', 'title': 'Conversation', 'kind': 'moment',
                'quote': 'Original caption.', 'start': 100.25, 'end': 106.75,
                'clip_title': 'Building a consistent routine', 'summary': 'The speaker describes a daily routine.'}
        collections = [{'id': 'a', 'name': 'Learning', 'items': [item]}]
        self.accounts.save_collections('alice', 0, collections)
        self.assertEqual(Accounts(self.path).collections('alice')['items'], collections)

    def test_invalid_saved_clip_descriptions_cannot_overwrite_existing_data(self):
        for field, value in [('clip_title', 1), ('clip_title', 'x' * 81),
                             ('summary', None), ('summary', 'x' * 401)]:
            item = {'id': 'Y566_T-YlNQ', 'title': 'Conversation', 'kind': 'episode', field: value}
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.accounts.save_collections('alice', 0, [{'id': 'a', 'name': 'Learning', 'items': [item]}])
        self.assertEqual(self.accounts.collections('alice')['revision'], 0)

    def test_daily_limits_are_atomic_persistent_and_roll_back_on_global_limit(self):
        def reserve(_):
            try:
                self.accounts.reserve_question('alice', 3, 4)
                return True
            except UsageLimit:
                return False
        with ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(sum(pool.map(reserve, range(12))), 3)
        Accounts(self.path).reserve_question('bob', 3, 4)
        with self.assertRaises(UsageLimit):
            self.accounts.reserve_question('charlie', 3, 4)
        with self.accounts.connect() as db:
            self.assertIsNone(db.execute("SELECT * FROM usage WHERE owner_id='charlie'").fetchone())

    def test_concurrent_guests_share_an_atomic_network_allowance(self):
        def reserve(number):
            try:
                self.accounts.reserve_question(f'guest-{number}', 3, 20, network_id='same-network')
                return True
            except UsageLimit:
                return False
        with ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(sum(pool.map(reserve, range(12))), 3)
