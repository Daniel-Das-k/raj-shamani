from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from knowledge.server import Demo


class LocalServerBusyTests(unittest.TestCase):
    def test_local_requests_fail_promptly_while_import_or_another_request_owns_runtime(self):
        with tempfile.TemporaryDirectory() as directory, patch('knowledge.server.load_settings'):
            demo = Demo(Path(directory), Path(directory) / 'links.txt', embedder=Mock(), llm=Mock())
            with demo.runtime_lock:
                for method in (demo.answer, demo.search):
                    with self.subTest(method=method.__name__), self.assertRaisesRegex(ValueError, 'busy'):
                        method('Explain focus')
            # The rejected call must neither release someone else's lock nor retain its own.
            self.assertEqual(demo.search('Explain focus'), {'excerpts': []})
            self.assertFalse(demo.runtime_lock.locked())
