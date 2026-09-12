"""Caption evidence must remain exact even if retrieved text or IDs are corrupted."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from knowledge.supermemory_captions import caption_source, resolve_hit, search_captions, upload_captions


class CaptionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.info = {"id": "abcdefghijk", "title": "Synthetic video"}
        self.raw = {"events": [
            {"tStartMs": 12345, "dDurationMs": 2000, "segs": [{"utf8": "Do not skip sleep."}]},
            {"tStartMs": 15000, "dDurationMs": 2000, "segs": [{"utf8": "Keep a regular bedtime."}]},
            {"tStartMs": 18000, "dDurationMs": 2000, "segs": [{"utf8": "Rest helps focus."}]},
        ]}
        self.source = caption_source(self.info, self.raw, "en-orig")

    def hit(self, text):
        return {"chunk": text, "metadata": {"video_id": self.source["id"], "revision": self.source["revision"]}}

    def test_exact_caption_text_produces_native_timestamps_and_video_link(self):
        hit = self.hit("[C000000] Do not skip sleep.\n[C000001] Keep a regular bedtime.")
        cites = resolve_hit(hit, self.source)
        self.assertEqual(len(cites), 1)
        self.assertEqual(cites[0]["start"], 12.345)
        self.assertEqual(cites[0]["end"], 17)
        self.assertEqual(cites[0]["url"], "https://www.youtube.com/watch?v=abcdefghijk&t=12s")
        self.assertEqual(cites[0]["quote"], "Do not skip sleep. Keep a regular bedtime.")
        self.assertEqual(cites[0]["timestamp_kind"], "youtube_caption_segment")
        self.assertFalse(cites[0]["human_verified"])

    def test_forged_words_unknown_ids_and_partial_segments_are_not_cited(self):
        for text in ("[C000000] Skip sleep.", "[C999999] Do not skip sleep.",
                     "[C000000] Do not skip", "Do not skip sleep."):
            with self.subTest(text=text):
                self.assertEqual(resolve_hit(self.hit(text), self.source), [])

    def test_wrong_video_and_stale_revision_are_rejected(self):
        for field in ("video_id", "revision"):
            hit = self.hit("[C000000] Do not skip sleep.")
            hit["metadata"][field] = "wrong"
            self.assertEqual(resolve_hit(hit, self.source), [])

    def test_nonadjacent_segments_remain_separate_citations(self):
        cites = resolve_hit(self.hit("[C000000] Do not skip sleep.\n[C000002] Rest helps focus."), self.source)
        self.assertEqual(len(cites), 2)
        self.assertEqual([c["segment_ids"] for c in cites], [["C000000"], ["C000002"]])

    def test_invalid_timestamps_are_rejected(self):
        for start, duration in ((-1, 2), (0, -2), (0, float("nan")), (float("inf"), 2)):
            raw = copy.deepcopy(self.raw)
            raw["events"][0].update(tStartMs=start, dDurationMs=duration)
            with self.assertRaises(ValueError):
                caption_source(self.info, raw, "en-orig")

    def test_upload_keeps_local_originals_and_skips_unchanged_transcripts(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            caps = directory / "captions"
            caps.mkdir()
            (caps / "abcdefghijk.info.json").write_text(json.dumps(self.info))
            (caps / "abcdefghijk.en-orig.json3").write_text(json.dumps(self.raw))
            client = Mock(container="caption-trial")
            client.add.return_value = {"id": "remote-document"}
            first = upload_captions(client, directory / "index", caps)
            second = upload_captions(client, directory / "index", caps)
            self.assertEqual(first, second)
            self.assertEqual(client.add.call_count, 1)
            self.assertIn("[C000000] Do not skip sleep.", client.add.call_args.args[0])
            self.assertEqual(client.add.call_args.args[2]["timestamp_kind"], "youtube_caption_segment")
            original = directory / "index" / f"abcdefghijk-{self.source['revision'][:12]}.json"
            self.assertEqual(json.loads(original.read_text())["segments"], self.source["segments"])

    def test_video_filter_is_sent_and_wrong_source_results_are_discarded(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            record = {"revision": self.source["revision"]}
            (directory / "manifest.json").write_text(json.dumps({"sources": {"abcdefghijk": record}}))
            original = directory / f"abcdefghijk-{self.source['revision'][:12]}.json"
            original.write_text(json.dumps(self.source))
            wrong = self.hit("[C000000] Do not skip sleep.")
            wrong["metadata"]["video_id"] = "lmnopqrstuv"
            client = Mock()
            client.search.return_value = {"results": [wrong, self.hit("[C000000] Do not skip sleep.")]}
            result = search_captions(client, directory, "sleep", "abcdefghijk")
            self.assertEqual(len(result["citations"]), 1)
            self.assertEqual(client.search.call_args.kwargs["filters"],
                             {"AND": [{"key": "video_id", "value": "abcdefghijk"}]})
            with self.assertRaisesRegex(ValueError, "not in the caption collection"):
                search_captions(client, directory, "sleep", "unknown")


if __name__ == "__main__":
    unittest.main()
