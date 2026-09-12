import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from knowledge.import_budget import BudgetStop, ImportBudget
from knowledge.channel_store import ChannelStore


class ImportBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'import-budget.json'
        self.path.write_text(json.dumps({'minimum_balance_usd': '0.86', 'max_new_documents': 100, 'reset_date': 'next-month'}))
        self.budget = ImportBudget(self.path)

    def client(self, balance='3.86', **changes):
        client = Mock()
        client.request.side_effect = [
            {'plan': 'free', 'resetDate': 'next-month', 'credits': {'balance': balance, 'label': 'USD'}, **changes},
            {'hasPaymentMethod': False, 'autoTopup': None}]
        return client

    def test_sufficient_balance_reserves_slot_persistently(self):
        self.budget.authorize(self.client(), 'hello')
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved['submitted'], 1)
        self.assertEqual(saved['last_balance_usd'], '3.86')
        self.assertEqual(saved['last_allowance_usd'], '0.010005')

    def test_checks_full_next_document_and_utf8_before_spending(self):
        with self.assertRaises(BudgetStop):
            self.budget.authorize(self.client('0.88'), 'न' * 10000)
        self.assertNotIn('submitted', json.loads(self.path.read_text()))

    def test_unreadable_or_invalid_balance_fails_closed(self):
        for balance in [None, 'NaN', 'Infinity', -1, 'unknown']:
            with self.subTest(balance=balance), self.assertRaises(BudgetStop):
                self.budget.authorize(self.client(balance), 'hello')
        client = Mock()
        client.request.side_effect = RuntimeError('unavailable')
        with self.assertRaises(BudgetStop):
            self.budget.authorize(client, 'hello')

    def test_cannot_silently_continue_on_paid_plan_or_new_period(self):
        for changes in [{'plan': 'pro'}, {'resetDate': 'another-month'}]:
            with self.assertRaises(BudgetStop):
                self.budget.authorize(self.client(**changes), 'hello')
        client = self.client()
        client.request.side_effect = [
            {'plan': 'free', 'resetDate': 'next-month'},
            {'hasPaymentMethod': True, 'autoTopup': {'enabled': True}}]
        with self.assertRaises(BudgetStop):
            self.budget.authorize(client, 'hello')

    def test_stop_and_document_limit_persist_across_restart(self):
        self.budget.stop('Review credits')
        client = Mock()
        with self.assertRaisesRegex(BudgetStop, 'Review credits'):
            ImportBudget(self.path).authorize(client, 'hello')
        client.request.assert_not_called()
        self.path.write_text(json.dumps({'minimum_balance_usd': '0.86', 'max_new_documents': 1, 'submitted': 1}))
        with self.assertRaises(BudgetStop):
            self.budget.authorize(client, 'hello')
        client.request.assert_not_called()

    def test_serial_queue_waits_for_inflight_document(self):
        store = ChannelStore(Path(self.temp.name) / 'channels.sqlite3')
        for vid in ['first', 'second']:
            store.add_video({'id': vid, 'title': vid, 'url': 'https://youtube.com/' + vid})
        store.update_video('first', state='indexing', next_attempt=10**12)
        self.assertIsNone(store.next_video(serial=True))
        store.update_video('first', state='ready')
        self.assertEqual(store.next_video(serial=True)['id'], 'second')

    def test_snapshot_order_overrides_retry_order_and_excludes_older_videos(self):
        store = ChannelStore(Path(self.temp.name) / 'channels.sqlite3')
        for vid in ['old', 'second', 'newest']:
            store.add_video({'id': vid, 'title': vid, 'url': 'https://youtube.com/' + vid})
        selection = ['newest', 'second']
        self.assertEqual(store.next_video(video_ids=selection)['id'], 'newest')
        store.update_video('newest', state='ready')
        self.assertEqual(store.next_video(video_ids=selection)['id'], 'second')
        store.update_video('second', state='ready')
        self.assertIsNone(store.next_video(video_ids=selection))
        self.assertIsNone(store.next_video(video_ids=[]))
        self.assertEqual(store.next_video()['id'], 'old')

    def test_video_selection_fails_closed_and_stops_at_completed_target(self):
        config = json.loads(self.path.read_text())
        config.update(target_ready_videos=100, video_ids=['abcdefghijk'])
        self.path.write_text(json.dumps(config))
        self.assertEqual(self.budget.video_ids(99), ['abcdefghijk'])
        with self.assertRaisesRegex(BudgetStop, '100 videos indexed'):
            self.budget.video_ids(100)
        config['video_ids'] = ['invalid']
        self.path.write_text(json.dumps(config))
        with self.assertRaises(BudgetStop):
            self.budget.video_ids(99)
        config['stopped'] = True
        self.path.write_text(json.dumps(config))
        self.assertEqual(self.budget.video_ids(99), [])
