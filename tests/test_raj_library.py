import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from knowledge.raj_library import CHANNEL_ID, RajShamaniLibrary
from knowledge.server import handler_for


class RajLibraryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.youtube, self.client = Mock(), Mock()
        self.library = RajShamaniLibrary(Path(temp.name), youtube=self.youtube,
                                        client_factory=lambda: self.client)
        self.store = self.library.store
        self.store.add_channel({"id": CHANNEL_ID, "title": "Raj Shamani",
                               "url": "https://www.youtube.com/@rajshamani"})
        self.store.add_channel({"id": "other", "title": "Other channel",
                               "url": "https://www.youtube.com/@other"})
        for i in range(52):
            self.video(f"video{i:06d}", CHANNEL_ID, "ready")
        self.video("pending0001", CHANNEL_ID, "queued")
        self.video("outside0001", "other", "ready")
        self.video("unowned0001", None, "ready")

    def video(self, video_id, channel, state):
        self.store.add_video({"id": video_id, "title": video_id,
                              "url": "https://www.youtube.com/watch?v=" + video_id})
        self.store.update_video(video_id, state=state)
        if channel:
            self.store.execute("INSERT INTO channel_videos VALUES(?,?)", (channel, video_id))

    def test_catalog_counts_and_pages_only_include_indexed_channel_members(self):
        status = self.library.status()
        self.assertTrue(status["read_only"])
        self.assertEqual(status["counts"], {"ready": 52})
        self.assertEqual(status["total"], 52)
        self.assertEqual(len(status["sources"]), 50)
        second = self.library.page(50)
        self.assertEqual(len(second), 2)
        ids = {v["id"] for v in status["sources"] + second}
        self.assertEqual(ids, {f"video{i:06d}" for i in range(52)})
        with self.assertRaises(ValueError):
            self.library.page(status="pending")

    def test_start_and_import_calls_cannot_resume_or_mutate_queue(self):
        before = self.store.status()
        self.library.start()
        self.assertIsNone(self.library.thread)
        self.assertFalse(self.library.step())
        for method, args in [("preview", ["@other"]), ("add_channel", [CHANNEL_ID]),
                             ("action", [CHANNEL_ID, "resume"]), ("start_ingestion", [[]])]:
            with self.subTest(method=method), self.assertRaisesRegex(ValueError, "Imports are disabled"):
                getattr(self.library, method)(*args)
        self.assertEqual(self.store.status(), before)
        self.assertEqual(self.youtube.mock_calls, [])
        self.assertEqual(self.client.mock_calls, [])

    def test_search_rejects_outside_and_pending_selections_and_remote_hits(self):
        for video in ["outside0001", "unowned0001", "pending0001"]:
            with self.subTest(video=video), self.assertRaises(ValueError):
                self.library.search("Explain leadership", video)
        self.client.search.assert_not_called()
        self.client.search.return_value = {"results": [
            {"metadata": {"video_id": "outside0001"}},
            {"metadata": {"video_id": "pending0001"}}]}
        self.assertEqual(self.library.search("Explain leadership"), {"excerpts": []})

    def handler(self):
        cls = handler_for(self.library)
        handler = cls.__new__(cls)
        handler.allowed_request = Mock(return_value=True)
        handler.send_data = Mock()
        return handler

    def test_http_import_routes_are_disabled_even_when_called_directly(self):
        for route in ["/api/ingest", "/api/channels/preview", "/api/channels", "/api/channels/action"]:
            handler = self.handler()
            handler.path = route
            handler.headers = {"Content-Type": "application/json", "Content-Length": "2"}
            handler.rfile = io.BytesIO(b"{}")
            with patch("knowledge.server.load_settings"):
                handler.do_POST()
            self.assertEqual(handler.send_data.call_args.args[1], 403)

    def test_http_pagination_uses_scoped_library(self):
        handler = self.handler()
        handler.path = "/api/videos?offset=50"
        handler.do_GET()
        rows = handler.send_data.call_args.args[0]["sources"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["id"].startswith("video") for row in rows))
