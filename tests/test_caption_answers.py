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

    def test_whole_passage_ids_can_be_resolved_without_generated_segment_numbers(self):
        span = self.raw["points"][0]["evidence"][0]
        del span["start_segment"], span["end_segment"]
        answer = validate_caption_answer(self.raw, self.passages, self.sources, whole_passages=True)
        self.assertEqual(answer["points"][0]["citations"][0]["segment_ids"], ["C000000", "C000001"])
        with self.assertRaises(KeyError):
            validate_caption_answer(self.raw, self.passages, self.sources)

    def test_structured_generation_limits_citations_to_retrieved_passages(self):
        raw = copy.deepcopy(self.raw)
        span = raw["points"][0]["evidence"][0]
        del span["start_segment"], span["end_segment"]
        span["summary"] = "Consider your schedule."
        class StructuredLLM:
            supports_schema = True
            def complete(inner, system, data, *, schema):
                if "items" not in data:
                    inner.generation_schema = schema
                    return raw
                return {"checks": {str(i["id"]): {"supported": True, "reason": "Supported",
                    "unsupported_claims": [], "evidence_ids": ["E0:S0"]} for i in data["items"]}}
        llm = StructuredLLM()
        result = answer_captions("Who?", self.citations, self.sources, llm, whole_passages=True)
        self.assertEqual(result["status"], "answered")
        evidence = llm.generation_schema["properties"]["points"]["items"]["properties"]["evidence"]
        self.assertEqual(evidence["maxItems"], 3)
        self.assertEqual(evidence["items"]["properties"]["passage_id"]["enum"], ["P0"])
        self.assertNotIn("start_segment", evidence["items"]["properties"])

    def test_verified_answer_and_rejected_support(self):
        for supported in [True, False]:
            llm = Mock()
            llm.complete.side_effect = [self.raw, {"checks": [{"id": 0, "supported": supported}]}]
            result = answer_captions("Is it for everyone?", self.citations, self.sources, llm)
            self.assertEqual(result["status"], "answered" if supported else "invalid_evidence")

    def test_isolated_summary_cannot_read_question_draft_or_other_clips(self):
        self.raw['points'][0]['evidence'][0]['summary'] = 'An unrelated fact copied from another clip.'
        llm = Mock()
        llm.complete.side_effect = [self.raw, {'summary': 'Consider your own schedule.'},
            {'checks': [{'id': 0, 'supported': True}, {'id': 1, 'supported': True}]}]
        result = answer_captions('Is it for everyone?', self.citations, self.sources, llm, isolate_summaries=True)
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['points'][0]['citations'][0]['summary'], 'Consider your own schedule.')
        summary_input = llm.complete.call_args_list[1].args[1]
        self.assertEqual(summary_input, {'output_language': 'English',
            'reference_excerpt': {'text': self.citations[0]['quote']}})
        checked = llm.complete.call_args_list[2].args[1]['items']
        self.assertEqual(checked[1]['text'], 'Consider your own schedule.')

    def test_failed_isolated_summary_still_withholds_the_answer(self):
        llm = Mock()
        llm.complete.side_effect = [self.raw, {'summary': 'Everyone must do this.'},
            {'checks': [{'id': 0, 'supported': True}, {'id': 1, 'supported': False}]}]
        result = answer_captions('Is it for everyone?', self.citations, self.sources, llm, isolate_summaries=True)
        self.assertEqual(result['status'], 'invalid_evidence')
        self.assertEqual(result['points'], [])

    def test_isolated_summary_wrong_language_is_not_displayed(self):
        raw = copy.deepcopy(self.raw)
        raw['points'][0]['text'] = 'இது அனைவருக்கும் பொருந்தாது.'
        llm = Mock()
        llm.complete.side_effect = [raw, {'summary': 'Consider your own schedule.'}]
        result = answer_captions('இது அனைவருக்கும் பொருந்துமா?', self.citations, self.sources, llm, isolate_summaries=True)
        self.assertEqual(result['status'], 'invalid_evidence')
        self.assertEqual(llm.complete.call_count, 2)

    def test_identical_references_share_one_isolated_reading(self):
        raw = copy.deepcopy(self.raw)
        raw['points'][0]['evidence'].append(copy.deepcopy(raw['points'][0]['evidence'][0]))
        llm = Mock()
        llm.complete.side_effect = [raw, {'summary': 'Consider your own schedule.'},
            {'checks': [{'id': i, 'supported': True} for i in range(2)]}]
        result = answer_captions('Is it for everyone?', self.citations, self.sources, llm, isolate_summaries=True)
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(llm.complete.call_count, 3)

    def test_oversized_or_repetitive_paragraphs_require_repair(self):
        for text, repeat in [('x' * 901, False), ('Consider your schedule.', True)]:
            raw = copy.deepcopy(self.raw)
            raw['points'][0]['text'] = text
            if repeat:
                raw['points'].append(copy.deepcopy(raw['points'][0]))
            llm = Mock()
            llm.complete.return_value = raw
            result = answer_captions('Explain.', self.citations, self.sources, llm, isolate_summaries=True)
            self.assertEqual(result['status'], 'invalid_evidence')
            self.assertEqual(llm.complete.call_count, 1)

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

    def test_failed_summary_is_repaired_and_entire_replacement_verified(self):
        bad = copy.deepcopy(self.raw)
        bad["points"][0]["evidence"][0]["summary"] = "Everyone must do this."
        fixed = copy.deepcopy(bad)
        fixed["points"][0]["evidence"][0]["summary"] = "Consider your own schedule."
        llm = Mock()
        llm.complete.side_effect = [bad, {"checks": [{"id": 0, "supported": True},
            {"id": 1, "supported": False, "reason": "The excerpt says it is not for everyone."}]},
            fixed, {"checks": [{"id": 0, "supported": True}, {"id": 1, "supported": True}]}]
        audit = {}
        result = answer_captions("Does this suit everyone?", self.citations, self.sources, llm, audit, max_repairs=1)
        self.assertEqual(result["status"], "answered")
        self.assertTrue(audit["repaired"])
        self.assertEqual(len(audit["attempts"]), 2)
        feedback = llm.complete.call_args_list[2].args[1]
        self.assertEqual(feedback["checked_items"][1]["kind"], "reference_summary")
        self.assertIn("not for everyone", feedback["checks"]["checks"][1]["reason"])
        self.assertEqual(result["points"][0]["citations"][0]["quote"], self.citations[0]["quote"])

    def test_repair_never_bypasses_failed_verification_or_adds_unretrieved_evidence(self):
        llm = Mock()
        rejected = {"checks": [{"id": 0, "supported": False, "reason": "Unsupported"}]}
        llm.complete.side_effect = [self.raw, rejected, self.raw, rejected]
        result = answer_captions("Who?", self.citations, self.sources, llm, max_repairs=1)
        self.assertEqual(result["status"], "invalid_evidence")
        self.assertEqual(result["points"], [])
        self.assertEqual(llm.complete.call_count, 4)
        invalid = copy.deepcopy(self.raw)
        invalid["points"][0]["evidence"][0]["end_segment"] = "C999999"
        llm.complete.side_effect = [invalid, invalid]
        result = answer_captions("Who?", self.citations, self.sources, llm, max_repairs=1)
        self.assertEqual(result["status"], "invalid_evidence")

    def test_citation_format_can_be_repaired_but_corrupt_sources_cannot(self):
        bad = copy.deepcopy(self.raw)
        bad["points"][0]["evidence"] *= 4
        llm = Mock()
        llm.complete.side_effect = [bad, self.raw, {"checks": [{"id": 0, "supported": True}]}]
        result = answer_captions("Who?", self.citations, self.sources, llm, max_repairs=1)
        self.assertEqual(result["status"], "answered")
        self.citations[0]["quote"] = "Altered evidence"
        llm.reset_mock()
        result = answer_captions("Who?", self.citations, self.sources, llm, max_repairs=1)
        self.assertEqual(result["status"], "invalid_evidence")
        llm.complete.assert_not_called()

    def test_structured_verifier_requires_every_summary_and_rejects_false_checks(self):
        self.raw["points"][0]["evidence"][0]["summary"] = "Consider your schedule."
        answer = validate_caption_answer(self.raw, self.passages, self.sources)
        class StructuredLLM:
            supports_schema = True
            def complete(inner, system, data, *, schema):
                inner.schema = schema
                return inner.result
        llm = StructuredLLM()
        good = {"supported": True, "reason": "Supported by the excerpt", "unsupported_claims": [],
                "evidence_ids": ["E0:S0"]}
        for checks, expected in [({"0": good}, False),
                                 ({"0": good, "1": {"supported": False, "reason": "Overstatement"}}, False),
                                 ({"0": good, "1": good, "2": good}, False),
                                 ({"0": good, "1": good}, True)]:
            llm.result = {"checks": checks}
            self.assertEqual(verify_answer(answer, "Does this suit everyone?", llm), expected)
            self.assertEqual(llm.schema["properties"]["checks"]["required"], ["0", "1"])

    def test_each_sentence_is_checked_and_support_spans_cannot_be_forged(self):
        answer = validate_caption_answer(self.raw, self.passages, self.sources)
        answer["points"][0]["text"] = "Consider your schedule. This guarantees success."
        class StructuredLLM:
            supports_schema = True
            def complete(inner, system, data, *, schema):
                inner.items = data["items"]
                return {"checks": inner.checks}
        llm = StructuredLLM()
        good = {"supported": True, "reason": "Supported", "unsupported_claims": [],
                "evidence_ids": ["E0:S0"]}
        bad_checks = [
            {**good, "supported": False, "unsupported_claims": ["No success guarantee"]},
            {**good, "evidence_ids": []},
            {**good, "evidence_ids": ["E0:S999"]},
            {**good, "evidence_ids": ["E999:S0"]},
            {**good, "unsupported_claims": ["Unresolved cause"]},
        ]
        for bad in bad_checks:
            llm.checks = {"0": good, "1": bad}
            self.assertFalse(verify_answer(answer, "What should I consider?", llm))
            self.assertEqual([i["text"] for i in llm.items],
                             ["Consider your schedule.", "This guarantees success."])


if __name__ == "__main__":
    unittest.main()
