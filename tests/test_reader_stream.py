"""Offline HTTP regressions for progressive answers and persistent history."""
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from knowledge.server import handler_for
from knowledge.response_history import ResponseHistory


class ReaderStreamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.release = threading.Event()
        self.citation = {"source_id": "abcdefghijk", "title": "Memory conversation",
                         "start": 2, "end": 8, "quote": "Practice recall.",
                         "url": "https://www.youtube.com/watch?v=abcdefghijk&t=2s"}
        self.final = {"status": "answered", "points": [{"text": "Practice recall.", "citations": [self.citation]}]}
        self.demo = SimpleNamespace(data_dir=Path(self.temp.name), store=object(),
                                    llm=SimpleNamespace(model_name="offline-test"), answer=self.answer)
        self.settings = patch("knowledge.server.load_settings")
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.demo))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def answer(self, question, source_id=None, *, progress=None):
        self.assertEqual(question, "Explain memory")
        progress({"type": "stage", "message": "Searching"})
        progress({"type": "excerpts", "excerpts": [self.citation]})
        if not self.release.wait(5):
            raise RuntimeError("Test never released synthesis")
        return self.final

    def request(self):
        return Request(f"http://127.0.0.1:{self.server.server_port}/api/ask/stream",
                       data=json.dumps({"question": "Explain memory"}).encode(),
                       headers={"Content-Type": "application/json"})

    def test_excerpts_arrive_before_synthesis_and_final_answer_is_saved(self):
        with urlopen(self.request(), timeout=5) as response:
            self.assertIn("application/x-ndjson", response.headers["Content-Type"])
            self.assertEqual(json.loads(response.readline())["type"], "stage")
            event = json.loads(response.readline())
            self.assertEqual(event["excerpts"], [self.citation])
            self.assertFalse(self.release.is_set())
            self.release.set()
            final = json.loads(response.readline())
        self.assertEqual(final["type"], "answer")
        self.assertEqual(final["http_status"], 200)
        self.assertEqual(final["response"]["points"], self.final["points"])
        history = ResponseHistory(Path(self.temp.name) / "responses.sqlite3")
        self.assertEqual(history.get(final["response"]["record_id"])["response"], final["response"])

    def test_provider_failure_finishes_stream_with_safe_recorded_error(self):
        def fail(*args, **kwargs):
            raise RuntimeError("secret-provider-response")
        self.demo.answer = fail
        with urlopen(self.request(), timeout=5) as response:
            final = json.loads(response.readline())
        self.assertEqual(final["type"], "answer")
        self.assertEqual(final["http_status"], 500)
        self.assertNotIn("secret-provider-response", json.dumps(final))
        self.assertIn("record_id", final["response"])


if __name__ == "__main__":
    unittest.main()
