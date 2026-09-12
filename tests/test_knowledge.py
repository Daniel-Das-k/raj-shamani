"""Offline behavioral checks; all podcast text and model responses are synthetic."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from knowledge.answers import ask, validate_answer
from knowledge.ingest import ingest
from knowledge.store import Store
from knowledge.transcripts import chunk_words, citation, deepgram_words, youtube_source


def transcript(text="Talk to customers before building more features.", start=100):
    return {"results": {"channels": [{"alternatives": [{"words": [
        {"word": word, "punctuated_word": word, "start": start + i * .5,
         "end": start + i * .5 + .4, "speaker": 0, "confidence": .95, "speaker_confidence": .9}
        for i, word in enumerate(text.split())
    ]}]}]}}


class FakeEmbedder:
    """A controlled ranking fixture, not a semantic model quality evaluation."""
    model_name = "test-embedding"

    def encode(self, texts, *, query=False):
        return [[1.0, 0.0] if any(term in text.lower() for term in ("customer", "validation", "ग्राहक"))
                else [0.0, 1.0] for text in texts]


class FakeLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, system, data):
        self.calls.append((system, data))
        return self.responses.pop(0)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.words = deepgram_words(transcript())
        self.chunk = {**chunk_words("abcdefghijk", self.words, "revision")[0],
                      "url": "https://youtube.com/watch?v=abcdefghijk&t=999", "title": "Synthetic episode"}

    def test_url_variants_share_identity_and_discard_input_time(self):
        expected = {"id": "abcdefghijk", "url": "https://www.youtube.com/watch?v=abcdefghijk"}
        for url in ("https://youtu.be/abcdefghijk?t=45", "https://www.youtube.com/shorts/abcdefghijk",
                    "https://youtube.com/watch?v=abcdefghijk&list=xyz&t=200", "https://youtube.com/live/abcdefghijk"):
            self.assertEqual(youtube_source(url), expected)
        for url in ("https://youtube.com.evil.test/watch?v=abcdefghijk", "file:///etc/passwd",
                    "https://youtube.com/playlist?list=xyz", "https://youtu.be/nope"):
            with self.assertRaises(ValueError):
                youtube_source(url)

    def test_citation_is_derived_from_original_words(self):
        result = citation(self.chunk, 1, 3)
        self.assertEqual(result["quote"], "to customers before")
        self.assertEqual(result["start"], 100.5)
        self.assertEqual(result["end"], 101.9)
        self.assertEqual(result["url"], "https://www.youtube.com/watch?v=abcdefghijk&t=100s")
        self.assertFalse(result["human_verified"])

    def test_invalid_word_spans_cannot_produce_citations(self):
        for first, last in ((-1, 3), (0, 99), (4, 2), (1.0, 3), (True, 3), (None, 2)):
            with self.assertRaises(ValueError):
                citation(self.chunk, first, last)

    def test_hindi_and_low_confidence_survive(self):
        raw = transcript("पहले ग्राहक से बात करें।")
        raw["results"]["channels"][0]["alternatives"][0]["words"][0]["confidence"] = .3
        words = deepgram_words(raw)
        self.assertEqual(words[0]["text"], "पहले")
        self.assertIn("low confidence", words[0]["review_reasons"])

    def test_rejects_invalid_timestamps_and_empty_transcript(self):
        for start, end in ((-1, 0), (3, 2), (float("nan"), 2), (1, float("inf"))):
            raw = transcript()
            raw["results"]["channels"][0]["alternatives"][0]["words"][0].update(start=start, end=end)
            with self.assertRaises(ValueError):
                deepgram_words(raw)
        with self.assertRaises(ValueError):
            deepgram_words(transcript(""))

    def test_chunking_covers_long_episode_without_losing_word_positions(self):
        words = deepgram_words(transcript(" ".join(f"word{i}" for i in range(650))))
        chunks = chunk_words("abcdefghijk", words, "revision")
        self.assertEqual({w["index"] for c in chunks for w in c["words"]}, set(range(650)))
        self.assertTrue(all(c["end"] - c["start"] <= 45 and len(c["words"]) <= 100 for c in chunks))
        self.assertLess(chunks[1]["words"][0]["index"], chunks[0]["words"][-1]["index"])
        self.assertEqual(len({c["id"] for c in chunks}), len(chunks))

    def test_long_silence_does_not_create_duplicate_chunks(self):
        words = copy.deepcopy(self.words)
        for word in words[3:]:
            word["start"] += 90
            word["end"] += 90
        chunks = chunk_words("abcdefghijk", words, "revision")
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[1]["words"][0]["index"], 3)


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.store = Store(self.directory / "knowledge.sqlite3")
        self.embedder = FakeEmbedder()

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def add(self, source_id="abcdefghijk", text="Talk to customers before building more features.", revision="revision"):
        source = {**youtube_source(f"https://youtu.be/{source_id}"), "title": "Synthetic episode", "revision": revision}
        chunks = chunk_words(source_id, deepgram_words(transcript(text)), revision)
        self.store.replace(source, chunks, self.embedder.encode([c["text"] for c in chunks]), self.embedder.model_name)
        return {**chunks[0], "title": source["title"], "url": source["url"]}

    def test_multiple_sources_rank_by_vectors_and_preserve_links(self):
        self.add()
        self.add("lmnopqrstuv", "Choose a database after measuring query latency.")
        results = self.store.search(["customer validation"], self.embedder)
        self.assertEqual(len(self.store.sources()), 2)
        self.assertEqual(results[0]["source_id"], "abcdefghijk")
        self.assertIn("v=abcdefghijk", results[0]["url"])

    def test_reindex_replaces_both_vector_and_keyword_entries(self):
        self.add()
        self.add(text="Measure database latency.", revision="new-revision")
        self.assertEqual(self.store.sources()[0]["chunks"], 1)
        old = self.store.db.execute("SELECT id FROM chunk_search WHERE chunk_search MATCH 'customers'").fetchall()
        self.assertEqual(old, [])
        self.assertTrue(self.store.indexed("abcdefghijk", "new-revision", self.embedder.model_name))
        self.assertFalse(self.store.indexed("abcdefghijk", "revision", self.embedder.model_name))

    def test_failed_reindex_rolls_back_existing_collection(self):
        self.add()
        source = {**youtube_source("https://youtu.be/abcdefghijk"), "title": "Synthetic", "revision": "new"}
        chunk = chunk_words(source["id"], deepgram_words(transcript()), "new")[0]
        with self.assertRaises(Exception):
            self.store.replace(source, [chunk, chunk], [[1., 0.], [1., 0.]], self.embedder.model_name)
        self.assertTrue(self.store.indexed(source["id"], "revision", self.embedder.model_name))
        self.assertEqual(self.store.sources()[0]["chunks"], 1)

    def test_embedding_model_mismatch_is_not_silently_searched(self):
        self.add()
        changed = FakeEmbedder()
        changed.model_name = "different"
        with self.assertRaises(ValueError):
            self.store.search(["customers"], changed)

    def test_keyword_input_cannot_inject_fts_syntax(self):
        self.add()
        self.store.search(['customers OR " : ( ) * NEAR'], self.embedder)

    def test_empty_collection_avoids_model_calls(self):
        llm = FakeLLM()
        result = ask("How do I validate my product?", self.store, self.embedder, llm)
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(llm.calls, [])

    def test_vague_problem_returns_followup_without_search(self):
        self.add()
        llm = FakeLLM({"clarifying_question": "What part of running the company are you stuck on?", "queries": []})
        with patch.object(self.store, "search", side_effect=AssertionError("Should not search yet")):
            result = ask("I'm a 22-year-old technical founder and I'm stuck.", self.store, self.embedder, llm)
        self.assertEqual(result["status"], "needs_clarification")

    def answer_fixture(self, chunk):
        return {"status": "answered", "message": "One relevant passage was found.", "points": [
            {"text": "The speaker recommends customer conversations before more development.",
             "evidence": [{"chunk_id": chunk["id"], "start_word": 0, "end_word": 6}]}]}

    def test_question_to_answer_with_original_quote_and_timestamp(self):
        chunk = self.add()
        llm = FakeLLM({"clarifying_question": None, "queries": ["customer validation"]}, self.answer_fixture(chunk), {"checks": [{"id": 0, "supported": True}]})
        result = ask("I keep coding without knowing what customers need. What should I do?", self.store, self.embedder, llm)
        self.assertEqual(result["status"], "answered")
        cited = result["points"][0]["citations"][0]
        self.assertEqual(cited["quote"], "Talk to customers before building more features.")
        self.assertTrue(cited["url"].endswith("&t=100s"))
        self.assertEqual(len(llm.calls), 3)

    def test_invented_citation_fails_closed(self):
        chunk = self.add()
        answer = self.answer_fixture(chunk)
        answer["points"][0]["evidence"][0]["chunk_id"] = "invented"
        llm = FakeLLM({"clarifying_question": None, "queries": ["customers"]}, answer)
        result = ask("How can I validate customer demand?", self.store, self.embedder, llm)
        self.assertEqual(result["status"], "invalid_evidence")
        self.assertEqual(result["points"], [])

    def test_advice_without_evidence_is_rejected(self):
        chunk = self.add()
        answer = self.answer_fixture(chunk)
        answer["points"][0]["evidence"] = []
        with self.assertRaises(ValueError):
            validate_answer(answer, [chunk])

    def test_irrelevant_candidates_allow_abstention(self):
        self.add()
        llm = FakeLLM({"clarifying_question": None, "queries": ["hiring"]},
                      {"status": "insufficient_evidence", "message": "These passages do not address hiring.", "points": []})
        result = ask("How should I hire my first engineer?", self.store, self.embedder, llm)
        self.assertEqual(result["status"], "insufficient_evidence")

    def test_ingestion_reuses_only_matching_audio_cache(self):
        source = {**youtube_source("https://youtu.be/abcdefghijk"), "title": "Synthetic episode"}
        audio = self.directory / "audio.flac"
        audio.write_bytes(b"synthetic audio version one")
        with patch("knowledge.ingest.prepare", return_value=(audio, source)), \
                patch("knowledge.ingest.require_key", return_value="fake"), \
                patch("knowledge.ingest.transcribe", return_value=transcript()) as provider:
            first = ingest(source["url"], self.directory, self.store, self.embedder)
            second = ingest(source["url"], self.directory, self.store, self.embedder)
            self.assertEqual(first["status"], "indexed")
            self.assertEqual(second["status"], "already_indexed")
            self.assertEqual(provider.call_count, 1)
            audio.write_bytes(b"synthetic audio version two")
            ingest(source["url"], self.directory, self.store, self.embedder)
            self.assertEqual(provider.call_count, 2)
        caches = list((self.directory / "sources" / source["id"]).glob("deepgram-*.json"))
        self.assertEqual(len(caches), 2)
        self.assertIn("response", json.loads(caches[0].read_text()))


if __name__ == "__main__":
    unittest.main()
