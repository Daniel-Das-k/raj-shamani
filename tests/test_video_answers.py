"""General video Q&A checks with synthetic speech and no provider calls."""
import copy
from pathlib import Path
import tempfile
import unittest

from knowledge.answers import ask, render_answer, validate_answer, verify_answer
from knowledge.store import Store, keyword_tokens
from knowledge.transcripts import chunk_words, citation, deepgram_words, youtube_source
from knowledge.translations import translate_answer
from test_knowledge import FakeEmbedder, FakeLLM, transcript


class VideoAnswerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "collection.sqlite3")
        self.embedder = FakeEmbedder()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def add(self, video_id="abcdefghijk", text="Validation means testing demand before building.", start=100):
        source = {**youtube_source(f"https://youtu.be/{video_id}"), "title": video_id, "revision": "r1"}
        chunks = chunk_words(video_id, deepgram_words(transcript(text, start)), "r1")
        self.store.replace(source, chunks, self.embedder.encode([c["text"] for c in chunks]), self.embedder.model_name)
        return {**chunks[0], "title": source["title"], "url": source["url"]}

    def point(self, chunk, text=None):
        return {"text": text or chunk["text"], "evidence": [{"chunk_id": chunk["id"],
                "start_word": chunk["words"][0]["index"], "end_word": chunk["words"][-1]["index"]}]}

    def draft(self, *points):
        return {"status": "answered", "message": "A coverage note.", "points": list(points)}

    def plan(self, **changes):
        return {"clarifying_question": None, "queries": ["validation"], **changes}

    def test_factual_answer_needs_no_personal_obstacle_or_invented_action(self):
        chunk = self.add()
        llm = FakeLLM(self.plan(), self.draft(self.point(chunk)), {"checks": [{"id": 0, "supported": True}]})
        answer = ask("What does validation mean in these videos?", self.store, self.embedder, llm)
        self.assertEqual(answer["status"], "answered")
        self.assertEqual(answer["points"][0]["text"], chunk["text"])
        self.assertNotIn("suggested_application", answer["points"][0])
        self.assertIn(chunk["source_id"], str(llm.calls[0][1]["sources"]))
        self.assertIn("validation mean", llm.calls[0][1]["question"])
        rendered = render_answer(answer)
        self.assertIn(chunk["text"], rendered)
        self.assertIn("&t=100s", rendered)
        self.assertNotIn("Suggested action:", rendered)

    def test_comparison_preserves_each_video_link_and_fractional_time(self):
        first = self.add(start=100.25)
        second = self.add("lmnopqrstuv", "Validation can include measuring repeat purchases.", start=212.75)
        llm = FakeLLM(self.plan(broad=True), self.draft(self.point(first), self.point(second)),
                      {"checks": [{"id": 1, "supported": True}, {"id": 0, "supported": True}]})
        answer = ask("Compare the videos on validation.", self.store, self.embedder, llm)
        cites = [p["citations"][0] for p in answer["points"]]
        self.assertEqual([c["source_id"] for c in cites], ["abcdefghijk", "lmnopqrstuv"])
        self.assertEqual([c["start"] for c in cites], [100.25, 212.75])
        self.assertEqual([c["url"] for c in cites], [
            "https://www.youtube.com/watch?v=abcdefghijk&t=100s",
            "https://www.youtube.com/watch?v=lmnopqrstuv&t=212s"])
        self.assertEqual(cites[1]["video_url"], second["url"])
        self.assertEqual(cites[1]["end_word"], second["words"][-1]["index"])

    def test_semantically_unsupported_answer_is_withheld_despite_real_quote(self):
        chunk = self.add(text="Do not build before talking to customers.")
        llm = FakeLLM(self.plan(), self.draft(self.point(chunk, "Build before talking to customers.")),
                      {"checks": [{"id": 0, "supported": False}]})
        answer = ask("What does the video recommend?", self.store, self.embedder, llm)
        self.assertEqual(answer["status"], "invalid_evidence")
        self.assertEqual(answer["points"], [])
        self.assertEqual(llm.calls[-1][1]["items"][0]["excerpt_ids"], ["E0"])
        self.assertEqual(llm.calls[-1][1]["excerpts"][0]["quote"], chunk["text"])

    def test_verifier_requires_explicit_support_for_every_point(self):
        chunk = self.add()
        answer = validate_answer(self.draft(self.point(chunk), self.point(chunk)), [chunk])
        for checks in (None, [], [{"id": 0, "supported": True}],
                       [{"id": 0, "supported": True}] * 2,
                       [{"id": False, "supported": True}, {"id": 1, "supported": True}],
                       [{"id": 0, "supported": "true"}, {"id": 1, "supported": True}],
                       [{"id": 0, "supported": True}, {"id": 2, "supported": True}]):
            with self.subTest(checks=checks):
                self.assertFalse(verify_answer(answer, "What is validation?", FakeLLM({"checks": checks})))

    def test_model_cannot_put_uncited_answer_in_coverage_note(self):
        chunk = self.add()
        draft = self.draft(self.point(chunk))
        draft["message"] = "Uncited invented claim."
        self.assertNotIn("invented claim", validate_answer(draft, [chunk])["message"])

    def test_named_video_filter_applies_to_both_retrieval_and_answer_context(self):
        self.add()
        chosen = self.add("lmnopqrstuv", "Measure query latency first.")
        llm = FakeLLM(self.plan(source_ids=[chosen["source_id"]]),
                      self.draft(self.point(chosen)), {"checks": [{"id": 0, "supported": True}]})
        answer = ask("What does lmnopqrstuv recommend measuring?", self.store, self.embedder, llm)
        self.assertEqual(answer["status"], "answered")
        self.assertEqual({p["id"] for p in llm.calls[1][1]["passages"]}, {chosen["id"]})
        self.assertEqual(self.store.search(["validation"], self.embedder, source_ids=["nonexistent"]), [])

    def test_unknown_planned_video_is_not_silently_replaced(self):
        self.add()
        with self.assertRaisesRegex(ValueError, "unknown video"):
            ask("What does the other video say?", self.store, self.embedder,
                FakeLLM(self.plan(source_ids=["lmnopqrstuv"])))

    def test_broad_search_includes_small_video_beside_long_episode(self):
        self.add(text=" ".join(["customer"] * 3500))
        self.add("lmnopqrstuv", "Measure query latency first.")
        results = self.store.search(["customer"], self.embedder, limit=4, diversify=True)
        self.assertEqual({p["source_id"] for p in results[:2]}, {"abcdefghijk", "lmnopqrstuv"})

    def test_hindi_words_are_kept_intact_and_keyword_search_breaks_vector_tie(self):
        class FlatEmbedder:
            model_name = "test-embedding"

            def encode(self, texts, *, query=False):
                return [[1., 0.] for _ in texts]

        self.embedder = FlatEmbedder()
        self.add(text="बात करें")
        self.add("lmnopqrstuv", "पहले ग्राहक से बात करें")
        self.assertEqual(keyword_tokens("पहले ग्राहक से बात करें"), ["पहले", "ग्राहक", "से", "बात", "करें"])
        result = self.store.search(["ग्राहक"], self.embedder, limit=1)
        self.assertEqual(result[0]["source_id"], "lmnopqrstuv")

    def test_citation_rejects_missing_interior_words_and_huge_range(self):
        chunk = self.add()
        broken = copy.deepcopy(chunk)
        del broken["words"][1]
        for passage, last in ((broken, 2), (chunk, 10**12)):
            with self.assertRaises(ValueError):
                citation(passage, 0, last)

    def test_translation_caches_original_evidence_without_changing_links(self):
        chunk = self.add(text="पहले ग्राहक से बात करें")
        answer = validate_answer(self.draft(self.point(chunk)), [chunk])

        class Translator:
            calls = 0

            def complete(self, system, data):
                self.calls += 1
                return {"translations": [{"id": row["id"], "english_text": "Talk to customers first.",
                                          "source_languages": ["hi"]} for row in data["items"]]}

        llm = Translator()
        first = translate_answer(answer, self.store, llm)
        second = translate_answer(answer, self.store, llm)
        self.assertEqual(llm.calls, 1)
        self.assertEqual(first, second)
        original = answer["points"][0]["citations"][0]
        translated = first["points"][0]["citations"][0]
        for key, value in original.items():
            self.assertEqual(translated[key], value)
        self.assertEqual(translated["english_translation"], "Talk to customers first.")

    def test_translation_failure_keeps_answer_and_original_citation(self):
        chunk = self.add()
        answer = validate_answer(self.draft(self.point(chunk)), [chunk])
        result = translate_answer(answer, self.store, FakeLLM({"translations": []}))
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["points"][0]["citations"][0]["quote"], chunk["text"])
        self.assertEqual(result["points"][0]["citations"][0]["translation_status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
