import json
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest

from deployment.backup import make_backup
from deployment.seed import seed
from knowledge.accounts import Accounts
from knowledge.channel_store import ChannelStore
from knowledge.response_history import ResponseHistory


class DeploymentStorageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'snapshot'
        self.data = self.root / 'persistent'
        store = ChannelStore(self.source / 'channels.sqlite3')
        store.add_channel({'id': 'UCzwCEE_PchiBULMnAJqhGVg', 'title': 'Channel', 'url': 'https://youtube.com/test', 'handle': '@test'})
        store.add_video({'id': 'abcdefghijk', 'title': 'Video', 'url': 'https://youtu.be/abcdefghijk'}, 'UCzwCEE_PchiBULMnAJqhGVg')
        store.update_video('abcdefghijk', state='ready', revision='abcdef123456789', segments=1)
        caption = self.source / 'supermemory-trial/timed-captions/abcdefghijk-abcdef123456.json'
        caption.parent.mkdir(parents=True)
        caption.write_text(json.dumps({'id': 'abcdefghijk', 'revision': 'abcdef123456789', 'segments': [{'id': 'C0', 'text': 'Original'}]}))

    def test_seed_initializes_empty_disk_and_preserves_user_data_on_redeploy(self):
        seed(self.source, self.data)
        history = ResponseHistory(self.data / 'responses.sqlite3').for_owner('alice')
        history.save({'id': 'a'*32, 'created_at': '2026', 'question': 'Private', 'status': 'answered'})
        seed(self.source, self.data)
        self.assertEqual(ResponseHistory(self.data / 'responses.sqlite3').for_owner('alice').list()['total'], 1)
        self.assertFalse((self.data / '.env').exists())

    def test_corrupted_existing_caption_is_not_silently_overwritten(self):
        seed(self.source, self.data)
        caption = self.data / 'supermemory-trial/timed-captions/abcdefghijk-abcdef123456.json'
        caption.write_text('{}')
        with self.assertRaises(RuntimeError):
            seed(self.source, self.data)
        self.assertEqual(caption.read_text(), '{}')

    def test_backup_restores_owned_history_collections_and_original_captions(self):
        seed(self.source, self.data)
        history = ResponseHistory(self.data / 'responses.sqlite3').for_owner('alice')
        history.save({'id': 'a'*32, 'created_at': '2026', 'question': 'Private', 'status': 'answered'})
        accounts = Accounts(self.data / 'accounts.sqlite3')
        accounts.save_collections('alice', 0, [{'id': 'one', 'name': 'Saved', 'items': []}])
        (self.data / '.env').write_text('SHOULD_NOT_BE_BACKED_UP=synthetic-secret')
        archive = self.root / 'backup.tar.gz'
        make_backup(self.data, archive)
        restored = self.root / 'restored'
        with tarfile.open(archive) as backup:
            self.assertNotIn('.env', backup.getnames())
            backup.extractall(restored, filter='data')
        self.assertEqual(ResponseHistory(restored / 'responses.sqlite3').for_owner('alice').list()['total'], 1)
        self.assertEqual(ResponseHistory(restored / 'responses.sqlite3').for_owner('bob').list()['total'], 0)
        self.assertEqual(Accounts(restored / 'accounts.sqlite3').collections('alice')['revision'], 1)
        self.assertTrue((restored / 'supermemory-trial/timed-captions/abcdefghijk-abcdef123456.json').exists())
        for name in ['channels.sqlite3', 'accounts.sqlite3', 'responses.sqlite3']:
            with sqlite3.connect(restored / name) as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
