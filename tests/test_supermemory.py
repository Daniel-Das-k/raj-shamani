"""Offline checks for isolated, resumable SuperRAG trials."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from knowledge.supermemory import Supermemory, control_trial, start_trial, trial_status


class SupermemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    @patch.dict("os.environ", {"SUPERMEMORY_API_KEY": "test-secret"})
    def test_upload_uses_superrag_and_scoped_container(self):
        session = Mock()
        session.request.return_value.status_code = 200
        session.request.return_value.json.return_value = {"id": "document", "status": "queued"}
        client = Supermemory("test-container", session)
        client.add("Original words", "stable-id", {"video_id": "abcdefghijk"})
        args, kwargs = session.request.call_args
        self.assertEqual(args, ("POST", "https://api.supermemory.ai/v3/documents"))
        self.assertEqual(kwargs["json"]["taskType"], "superrag")
        self.assertEqual(kwargs["json"]["containerTag"], "test-container")
        self.assertEqual(kwargs["json"]["customId"], "stable-id")
        self.assertFalse(kwargs["allow_redirects"])

    @patch.dict("os.environ", {"SUPERMEMORY_API_KEY": "test-secret"})
    def test_search_only_queries_trial_container(self):
        session = Mock()
        session.request.return_value.status_code = 200
        session.request.return_value.json.return_value = {"results": []}
        client = Supermemory("test-container", session)
        client.search("What was discussed?")
        payload = session.request.call_args.kwargs["json"]
        self.assertEqual(payload["containerTag"], "test-container")
        self.assertEqual(payload["searchMode"], "documents")
        self.assertEqual(session.request.call_args.args[1], "https://api.supermemory.ai/v4/search")

    @patch.dict("os.environ", {"SUPERMEMORY_API_KEY": "test-secret"})
    def test_http_errors_redact_key(self):
        session = Mock()
        session.request.return_value.status_code = 401
        session.request.return_value.text = "Rejected test-secret"
        with self.assertRaises(RuntimeError) as failure:
            Supermemory(session=session).search("test")
        self.assertIn("401", str(failure.exception))
        self.assertNotIn("test-secret", str(failure.exception))

    def test_restarting_trial_does_not_duplicate_uploads(self):
        client = Mock(container="test-container")
        client.add.return_value = {"id": "document", "status": "queued"}
        urls = ["https://youtu.be/abcdefghijk", "https://youtube.com/watch?v=abcdefghijk&t=10"]
        first = start_trial(client, self.directory, urls)
        second = start_trial(client, self.directory, urls)
        self.assertEqual(first, second)
        self.assertEqual(client.add.call_count, 1)
        self.assertEqual(client.add.call_args.args[0], "https://www.youtube.com/watch?v=abcdefghijk")
        self.assertFalse(client.add.call_args.args[2]["timestamp_verified"])

    def test_status_saves_raw_extraction_without_inventing_timestamps(self):
        client = Mock(container="test-container")
        client.add.return_value = {"id": "document", "status": "queued"}
        start_trial(client, self.directory, ["https://youtu.be/abcdefghijk"])
        client.document.return_value = {"id": "document", "status": "done", "content": "Untimed transcript."}
        result = trial_status(client, self.directory)
        self.assertFalse(result[0]["timestamp_strings_present"])
        self.assertNotIn("start", result[0])
        saved = json.loads((self.directory / "abcdefghijk.json").read_text())
        self.assertEqual(saved["content"], "Untimed transcript.")

    def test_control_is_labeled_reused_and_searched_only_when_ready(self):
        client = Mock(container="test-control")
        client.add.return_value = {"id": "control-document"}
        client.document.return_value = {"status": "queued"}
        queued = control_trial(client, self.directory)
        self.assertTrue(queued["synthetic"])
        client.search.assert_not_called()
        client.document.return_value = {"status": "done"}
        client.search.return_value = {"results": [{"documentId": "control-document"}]}
        client.search_v3.return_value = {"results": []}
        ready = control_trial(client, self.directory)
        self.assertEqual(client.add.call_count, 1)
        self.assertTrue(client.add.call_args.args[2]["synthetic"])
        self.assertEqual(ready["search"]["results"][0]["documentId"], "control-document")


if __name__ == "__main__":
    unittest.main()
