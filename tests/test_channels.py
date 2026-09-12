import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from knowledge.channel_library import ChannelLibrary
from knowledge.channel_store import ChannelStore
from knowledge.supermemory_captions import caption_source
from knowledge.youtube_channels import YouTube, channel_url

CHANNEL = "UCabcdefghijklmnopqrstuv"
VIDEO = "abcdefghijk"


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"SUPERMEMORY_API_KEY": "synthetic-test"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.youtube = Mock()
        self.youtube.preview.return_value = {"id": CHANNEL, "title": "Test channel", "url": "https://www.youtube.com/channel/" + CHANNEL, "sample": []}
        self.video = {"id": VIDEO, "title": "Test video", "url": "https://www.youtube.com/watch?v=" + VIDEO}
        self.youtube.uploads.return_value = iter([self.video, self.video])
        self.source = caption_source({"id": VIDEO, "title": "Test video"}, {"events": [
            {"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "Original evidence."}]}]}, "en-orig")
        self.youtube.captions.return_value = self.source
        self.client = Mock()
        self.client.add.return_value = {"id": "document"}
        self.client.document.return_value = {"status": "done"}
        self.library = ChannelLibrary(self.root, youtube=self.youtube, client_factory=lambda: self.client)

    def add_channel(self):
        self.library.preview("@example")
        self.library.add_channel(CHANNEL)

    def test_only_supported_youtube_channel_addresses_are_accepted(self):
        self.assertEqual(channel_url(" @rajshamani "), "https://www.youtube.com/@rajshamani")
        self.assertEqual(channel_url("https://www.youtube.com/@rajshamani/"), "https://www.youtube.com/@rajshamani")
        self.assertEqual(channel_url(CHANNEL), "https://www.youtube.com/channel/" + CHANNEL)
        for bad in ["https://example.com/@test", "https://youtube.com.evil.test/@test", "http://localhost/@test", "https://user@youtube.com/@test", "https://youtube.com:443/@test", "@test/../watch", "https://youtube.com/watch?v=" + VIDEO, None]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                channel_url(bad)

    def test_preview_does_not_queue_or_upload(self):
        self.library.preview("@example")
        self.assertEqual(self.library.status()["total"], 0)
        self.assertEqual(self.library.status()["channels"], [])
        self.client.add.assert_not_called()
        with self.assertRaises(ValueError):
            self.library.add_channel("unknown")

    def test_channel_discovery_uses_videos_tab_and_excludes_shorts(self):
        reader = YouTube()
        context = MagicMock()
        client = context.__enter__.return_value
        client.extract_info.return_value = {"entries": [
            {"id": VIDEO, "title": "Full episode"},
            {"id": "short000001", "url": "https://www.youtube.com/shorts/short000001"},
            {"id": "short000002", "media_type": "short"},
            {"id": "video000001", "duration": 90, "media_type": "video"},
        ]}
        with patch.object(reader, "client", return_value=context):
            videos = list(reader.uploads(CHANNEL))
        self.assertEqual([v["id"] for v in videos], [VIDEO, "video000001"])
        client.extract_info.assert_called_once_with("https://www.youtube.com/channel/" + CHANNEL + "/videos", download=False)

    def test_short_watch_link_is_rejected_before_fetching_captions(self):
        reader = YouTube()
        context = MagicMock()
        client = context.__enter__.return_value
        client.extract_info.return_value = {"id": VIDEO, "media_type": "short"}
        with patch.object(reader, "client", return_value=context), self.assertRaisesRegex(ValueError, "Shorts are excluded"):
            reader.captions(VIDEO)
        client.urlopen.assert_not_called()

    def test_explicit_short_url_does_not_queue_any_part_of_request(self):
        with self.assertRaisesRegex(ValueError, "Shorts are excluded"):
            self.library.start_ingestion([self.video["url"], "https://www.youtube.com/shorts/short000001"])
        self.assertEqual(self.library.status()["total"], 0)

    def test_cached_short_cannot_be_uploaded(self):
        self.library.store.add_video(self.video)
        (self.library.directory / (VIDEO + "-pending.json")).write_text(json.dumps({**self.source, "media_type": "short"}))
        self.library.step()
        self.client.add.assert_not_called()
        self.assertEqual(self.library.status()["counts"], {"skipped": 1})

    def test_rejected_reply_is_only_saved_as_redacted_local_diagnostic(self):
        self.library.search = Mock(return_value={"excerpts": []})
        def rejected(*args, audit, **kwargs):
            audit.update(raw_answer={"text": "unverified diagnostic-secret"}, validation_error="Unsupported claim")
            return {"status": "invalid_evidence", "points": [], "message": "Withheld"}
        with patch.dict(os.environ, {"GROQ_API_KEY": "diagnostic-secret"}), patch("knowledge.channel_library.answer_captions", side_effect=rejected):
            response = self.library.answer("A question")
        self.assertEqual(response["points"], [])
        self.assertNotIn("raw_answer", response)
        files = list((self.root / "response-diagnostics").glob("*.json"))
        self.assertEqual(len(files), 1)
        saved = files[0].read_text()
        self.assertIn("Unsupported claim", saved)
        self.assertNotIn("diagnostic-secret", saved)

    def test_discovery_is_deduplicated_and_ready_requires_provider_done(self):
        self.add_channel()
        self.library.step()
        self.assertEqual(self.library.status()["total"], 1)
        self.library.step()
        self.assertEqual(self.library.status()["counts"], {"indexing": 1})
        record = self.library.store.rows("SELECT * FROM videos")[0]
        self.assertTrue((self.library.directory / f"{VIDEO}-{record['revision'][:12]}.json").exists())
        self.library.store.update_video(VIDEO, next_attempt=0)
        self.library.step()
        self.assertEqual(self.library.status()["counts"], {"ready": 1})
        self.library.action(CHANNEL, "sync")
        self.youtube.uploads.return_value = iter([self.video])
        self.library.step()
        self.assertFalse(self.library.step())
        self.client.add.assert_called_once()

    def test_pause_resume_and_restart_keep_the_queue(self):
        self.add_channel()
        self.library.step()
        self.library.action(CHANNEL, "pause")
        self.assertFalse(self.library.step())
        reloaded = ChannelStore(self.root / "channels.sqlite3")
        self.assertEqual(reloaded.status()["counts"], {"queued": 1})
        self.library.action(CHANNEL, "resume")
        self.assertTrue(self.library.step())

    def test_recovery_does_not_reupload_a_known_remote_document(self):
        self.library.store.add_video(self.video)
        self.library.store.update_video(VIDEO, state="processing", document_id="existing")
        self.library.store.recover()
        self.library.step()
        self.client.add.assert_not_called()
        self.assertEqual(self.library.status()["counts"], {"ready": 1})

    def test_caption_failure_is_visible_and_retryable(self):
        self.add_channel()
        self.library.step()
        self.youtube.captions.side_effect = ValueError("No usable timed captions available.")
        self.library.step()
        self.assertEqual(self.library.status()["counts"], {"skipped": 1})
        self.client.add.assert_not_called()
        self.library.action(CHANNEL, "retry")
        self.assertEqual(self.library.status()["counts"], {"queued": 1})

    def test_lost_upload_response_retries_same_document_and_cached_captions(self):
        self.library.store.add_video(self.video)
        self.client.add.side_effect = [RuntimeError("network"), {"id": "document"}]
        self.library.step()
        self.library.store.update_video(VIDEO, next_attempt=0)
        self.library.step()
        self.assertEqual(self.client.add.call_args_list[0].args[1], self.client.add.call_args_list[1].args[1])
        self.youtube.captions.assert_called_once()

    def test_search_rejects_wrong_video_and_stale_revision(self):
        self.library.store.add_video(self.video)
        self.library.step()
        self.library.store.update_video(VIDEO, state="ready")
        good = {"metadata": {"video_id": VIDEO, "revision": self.source["revision"]}, "chunk": "[C000000] Original evidence."}
        self.client.search.return_value = {"results": [good, {**good, "metadata": {"video_id": VIDEO, "revision": "stale"}}]}
        result = self.library.search("evidence", VIDEO)
        self.assertEqual(len(result["excerpts"]), 1)
        self.assertEqual(result["excerpts"][0]["url"], self.video["url"] + "&t=1s")
        self.assertEqual(self.client.search.call_args.kwargs["filters"], {"AND": [{"key": "video_id", "value": VIDEO}]})
        with self.assertRaises(ValueError):
            self.library.search("evidence", "unknown")

    def test_failed_discovery_preserves_already_discovered_items(self):
        def broken():
            yield self.video
            raise RuntimeError("network")
        self.add_channel()
        self.youtube.uploads.return_value = broken()
        self.library.step()
        self.assertEqual(self.library.status()["channels"][0]["state"], "error")
        self.assertEqual(self.library.status()["total"], 1)

    def test_status_filter_applies_before_pagination(self):
        for index in range(53):
            video_id = f"video{index:06}"
            self.library.store.add_video({**self.video, "id": video_id})
            self.library.store.update_video(video_id, state="ready" if index < 51 else "queued")
        self.assertEqual(len(self.library.store.page(status="ready")), 50)
        second_page = self.library.store.page(50, status="ready")
        self.assertEqual(len(second_page), 1)
        self.assertEqual(second_page[0]["state"], "ready")
        self.assertEqual(len(self.library.store.page(status="pending")), 2)
        self.assertEqual(self.library.store.page(status="attention"), [])
        with self.assertRaises(ValueError):
            self.library.store.page(status="ready' OR 1=1 --")


if __name__ == "__main__":
    unittest.main()
