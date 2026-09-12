from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from knowledge.response_history import ResponseHistory
from knowledge.server import recorded_answer


class ResponseHistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "responses.sqlite3"
        self.history = ResponseHistory(self.path)
        self.answer = {"status": "answered", "message": "From the videos", "points": [{
            "text": "A recorded answer", "citations": [{"source_id": "abcdefghijk",
                "start": 12.5, "end": 18.25, "quote": "Original words.",
                "url": "https://www.youtube.com/watch?v=abcdefghijk&t=12s"}]}]}
        self.demo = SimpleNamespace(store=object(), llm=SimpleNamespace(model_name="test-model"), answer=Mock(return_value=self.answer))

    def test_success_preserves_exact_response_and_metadata_across_restart(self):
        body, status = recorded_answer(self.demo, self.history, {"question": "क्या कहा?", "source_id": "abcdefghijk"})
        self.assertEqual(status, 200)
        record = ResponseHistory(self.path).get(body["record_id"])
        self.assertEqual(record["response"], body)
        self.assertEqual(record["question"], "क्या कहा?")
        self.assertEqual(record["source_id"], "abcdefghijk")
        self.assertEqual(record["model"], "test-model")
        self.assertGreaterEqual(record["elapsed_seconds"], 0)
        self.assertEqual(record["response"]["points"], self.answer["points"])

    def test_rate_limit_records_safe_error_and_retry_interval_not_headers(self):
        error = RuntimeError("private provider error with credentials")
        error.status_code = 429
        error.response = SimpleNamespace(headers={"retry-after": "42", "Authorization": "secret-header"})
        self.demo.answer.side_effect = error
        body, status = recorded_answer(self.demo, self.history, {"question": "Explain focus"})
        record = self.history.get(body["record_id"])
        self.assertEqual(status, 500)
        self.assertEqual(record["status"], "error")
        self.assertEqual(record["provider_http_status"], 429)
        self.assertEqual(record["retry_after_seconds"], 42)
        self.assertIn("usage limit", body["error"])
        self.assertNotIn("private provider", json.dumps(record))
        self.assertNotIn("secret-header", json.dumps(record))

    def test_configured_credentials_are_redacted_from_stored_content(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "credential-not-for-logs"}):
            body, _ = recorded_answer(self.demo, self.history, {"question": "accidentally pasted credential-not-for-logs"})
        record = self.history.get(body["record_id"])
        self.assertNotIn("credential-not-for-logs", json.dumps(record))
        self.assertIn("[redacted]", record["question"])
        self.assertNotIn("credential-not-for-logs", json.dumps(self.history.list()))

    def test_openai_quota_failure_explains_billing_instead_of_waiting(self):
        for detail in ({"code": "insufficient_quota"}, {"error": {"code": "insufficient_quota"}}):
            error = RuntimeError("private provider error")
            error.status_code = 429
            error.body = detail
            self.demo.answer.side_effect = error
            body, _ = recorded_answer(self.demo, self.history, {"question": "Explain focus"})
            self.assertIn("billing", body["error"])
            self.assertNotIn("Wait a minute", body["error"])

    def test_concurrent_responses_are_unique_and_paginated_without_loss(self):
        def ask(index):
            return recorded_answer(self.demo, self.history, {"question": f"Question {index}"})[0]["record_id"]
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(ask, range(25)))
        self.assertEqual(len(set(ids)), 25)
        first, second = self.history.list(), self.history.list(offset=20)
        self.assertEqual(first["total"], 25)
        self.assertEqual(len(first["items"]), 20)
        self.assertEqual(len(second["items"]), 5)
        self.assertEqual({r["id"] for r in first["items"] + second["items"]}, set(ids))
        with self.assertRaises(ValueError):
            self.history.get("../.env")
        self.assertIsNone(self.history.get("0" * 32))

    def test_storage_failure_does_not_discard_answer_or_claim_it_was_saved(self):
        with patch.object(self.history, "save", side_effect=OSError("disk full")):
            body, status = recorded_answer(self.demo, self.history, {"question": "Explain focus"})
        self.assertEqual(status, 200)
        self.assertEqual(body["points"], self.answer["points"])
        self.assertNotIn("record_id", body)
        self.assertIn("recording_error", body)

    def test_abstentions_and_failed_evidence_checks_are_recorded(self):
        for state in ("insufficient_evidence", "invalid_evidence", "needs_clarification"):
            self.demo.answer.return_value = {"status": state, "points": [], "message": "No answer"}
            body, _ = recorded_answer(self.demo, self.history, {"question": "Explain focus"})
            self.assertEqual(self.history.get(body["record_id"])["status"], state)


if __name__ == "__main__":
    unittest.main()
