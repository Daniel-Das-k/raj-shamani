import copy
import unittest
from unittest.mock import Mock, patch

from knowledge.caption_answers import TrialGroq, answer_captions, build_passages, validate_caption_answer
from knowledge.answers import verify_answer
from knowledge.supermemory_captions import caption_source, resolve_hit


class CaptionAnswerTests(unittest.TestCase):
    def setUp(self):
        self.source = caption_source({"id": "abcdefghijk", "title": "Example episode"}, {"events": [
            {"tStartMs": 10000, "dDurationMs": 2000, "segs": [{"utf8": "It is not for everyone."}]},
            {"tStartMs": 12000, "dDurationMs": 2000, "segs": [{"utf8": "Consider your own schedule."}]},
            {"tStartMs": 14000, "dDurationMs": 2000, "segs": [{"utf8": "Rest matters."}]},
        ]}, "en")
        self.sources = {self.source["id"]: self.source}
        self.citations = resolve_hit({"metadata": {"video_id": self.source["id"], "revision": self.source["revision"]},
            "chunk": "[C000000] It is not for everyone.\n[C000001] Consider your own schedule."}, self.source)
        self.passages = build_passages(self.citations, self.sources)
        self.raw = {"status": "answered", "points": [{"text": "The episode says it is not for everyone.",
            "evidence": [{"passage_id": "P0", "start_segment": "C000000", "end_segment": "C000001"}]}]}

    def test_citation_timing_and_links_come_from_originals(self):
        result = validate_caption_answer(self.raw, self.passages, self.sources)
        citation = result["points"][0]["citations"][0]
        self.assertEqual((citation["start"], citation["end"]), (10, 14))
        self.assertTrue(citation["url"].endswith("&t=10s"))
        self.assertFalse(citation["human_verified"])

    def test_cannot_cite_unretrieved_or_invented_segments(self):
        for sid in ["C000002", "C999999"]:
            raw = copy.deepcopy(self.raw)
            raw["points"][0]["evidence"][0]["end_segment"] = sid
            llm = Mock()
            llm.complete.return_value = raw
            result = answer_captions("Who?", self.citations, self.sources, llm)
            self.assertEqual(result["status"], "invalid_evidence")
            self.assertEqual(result["points"], [])

    def test_reference_summary_preserves_original_evidence(self):
        self.raw["points"][0]["evidence"][0]["summary"] = "Consider whether this fits your schedule."
        result = validate_caption_answer(self.raw, self.passages, self.sources)
        citation = result["points"][0]["citations"][0]
        self.assertEqual(citation["summary"], "Consider whether this fits your schedule.")
        for key in ("quote", "start", "end", "url", "segment_ids"):
            self.assertEqual(citation[key], self.citations[0][key])
        for value in (None, "", "x" * 501):
            self.raw["points"][0]["evidence"][0]["summary"] = value
            with self.assertRaises(ValueError):
                validate_caption_answer(self.raw, self.passages, self.sources)

    def test_summary_requires_its_own_explicit_support(self):
        self.raw["points"][0]["evidence"][0]["summary"] = "Consider your own schedule."
        for extra in ([], [{"id": 1, "supported": False}], [{"id": 1, "supported": True}]):
            llm = Mock()
            llm.complete.side_effect = [self.raw, {"checks": [{"id": 0, "supported": True}, *extra]}]
            result = answer_captions("Is it for everyone?", self.citations, self.sources, llm)
            self.assertEqual(result["status"], "answered" if extra and extra[0]["supported"] else "invalid_evidence")
            items = llm.complete.call_args.args[1]["items"]
            self.assertEqual(items[1]["kind"], "reference_summary")
            self.assertEqual(items[1]["excerpt_ids"], ["E0"])
            self.assertEqual(llm.complete.call_args.args[1]["excerpts"][0]["quote"], self.citations[0]["quote"])

    def test_summary_checks_are_deduplicated_and_scoped_to_their_original(self):
        self.raw["points"][0]["evidence"][0]["summary"] = "Consider your own schedule."
        answer = validate_caption_answer(self.raw, self.passages, self.sources)
        answer["points"].append(copy.deepcopy(answer["points"][0]))
        second = copy.deepcopy(answer["points"][0]["citations"][0])
        second.update(quote="Rest matters.", summary="Rest is important.")
        answer["points"][1]["citations"].append(second)
        llm = Mock()
        llm.complete.return_value = {"checks": [{"id": i, "supported": True} for i in range(4)]}
        self.assertTrue(verify_answer(answer, "What matters?", llm))
        items = llm.complete.call_args.args[1]["items"]
        self.assertEqual(len(items), 4)  # Two paragraphs + two distinct reference summaries.
        self.assertEqual(items[2]["excerpt_ids"], ["E0"])
        self.assertEqual(items[3]["excerpt_ids"], ["E1"])
        excerpts = llm.complete.call_args.args[1]["excerpts"]
        self.assertEqual(len(excerpts), 2)
        self.assertEqual(excerpts[1], {"id": "E1", "title": second["title"], "quote": "Rest matters.", "speakers": []})

    def test_whole_passage_option_adds_context_but_still_rejects_invented_ids(self):
        self.raw["points"][0]["evidence"][0]["end_segment"] = "C000000"
        answer = validate_caption_answer(self.raw, self.passages, self.sources, whole_passages=True)
        self.assertEqual(answer["points"][0]["citations"][0]["segment_ids"], ["C000000", "C000001"])
        self.raw["points"][0]["evidence"][0]["end_segment"] = "C999999"
        with self.assertRaises(ValueError):
            validate_caption_answer(self.raw, self.passages, self.sources, whole_passages=True)

    def test_verified_answer_and_rejected_support(self):
        for supported in [True, False]:
            llm = Mock()
            llm.complete.side_effect = [self.raw, {"checks": [{"id": 0, "supported": supported}]}]
            result = answer_captions("Is it for everyone?", self.citations, self.sources, llm)
            self.assertEqual(result["status"], "answered" if supported else "invalid_evidence")

    def test_no_hits_abstains_without_model_call(self):
        llm = Mock()
        result = answer_captions("An unrelated question", [], self.sources, llm)
        self.assertEqual(result["status"], "insufficient_evidence")
        llm.complete.assert_not_called()

    def test_modified_quote_is_withheld(self):
        self.citations[0]["quote"] = "It is for everyone."
        llm = Mock()
        result = answer_captions("Who?", self.citations, self.sources, llm)
        self.assertEqual(result["status"], "invalid_evidence")
        llm.complete.assert_not_called()

    def test_changed_source_timing_is_withheld_before_generation(self):
        self.source["segments"][0]["start"] = 9
        llm = Mock()
        result = answer_captions("Who?", self.citations, self.sources, llm)
        self.assertEqual(result["status"], "invalid_evidence")
        llm.complete.assert_not_called()

    def test_noncontiguous_evidence_is_rejected(self):
        self.passages[0]["segments"] = [self.source["segments"][0], self.source["segments"][2]]
        self.raw["points"][0]["evidence"][0]["end_segment"] = "C000002"
        with self.assertRaises(ValueError):
            validate_caption_answer(self.raw, self.passages, self.sources)

    def test_rate_limit_retries_follow_retry_after(self):
        error = RuntimeError("synthetic rate limit")
        error.status_code = 429
        error.response = Mock(headers={"retry-after": "2"})
        with patch("knowledge.providers.GroqJSON.complete", side_effect=[error, {"ok": True}]) as call, \
                patch("knowledge.caption_answers.time.sleep") as sleep:
            self.assertEqual(TrialGroq(1).complete("prompt", {}), {"ok": True})
            sleep.assert_called_once_with(2.25)
            self.assertEqual(call.call_count, 2)

    def test_rate_limit_wait_is_bounded(self):
        error = RuntimeError("synthetic long wait")
        error.status_code = 429
        error.response = Mock(headers={"retry-after": "120"})
        with patch("knowledge.providers.GroqJSON.complete", side_effect=error), \
                patch("knowledge.caption_answers.time.sleep") as sleep:
            with self.assertRaises(RuntimeError):
                TrialGroq(1).complete("prompt", {})
            sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
