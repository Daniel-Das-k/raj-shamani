"""Keep diagnostic coverage measurements and context provenance honest."""
import unittest

from knowledge.analyze_supermemory import expand
from knowledge.evaluate_supermemory import score_anchors


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.source = {"id": "video", "url": "https://www.youtube.com/watch?v=video",
                       "segments": [{"id": f"C{i:06}", "text": str(i), "start": i * 2.5,
                                     "end": i * 2.5 + 3} for i in range(5)]}
        self.case = {"gold_groups": [{"video_id": "video", "start_segment": "C000001",
                                     "end_segment": "C000004"}]}

    def test_coverage_uses_unique_segments_from_the_correct_source(self):
        citations = [{"source_id": "other", "segment_ids": ["C000001", "C000002"]},
                     {"source_id": "video", "segment_ids": ["C000001", "C000002"]},
                     {"source_id": "video", "segment_ids": ["C000002"]},
                     {"source_id": "video", "segment_ids": ["C000003", "C000004"]}]
        score = score_anchors(self.case, citations, {"video": self.source})[0]
        self.assertEqual(score["top1_coverage"], 0)
        self.assertEqual(score["top3_coverage"], 0.5)
        self.assertEqual(score["all_coverage"], 1)

    def test_reversed_reference_span_is_rejected(self):
        self.case["gold_groups"][0].update(start_segment="C000004", end_segment="C000001")
        with self.assertRaises(ValueError):
            score_anchors(self.case, [], {"video": self.source})

    def test_neighbor_context_preserves_originals_and_updates_all_timing_fields(self):
        citation = {"source_id": "video", "segment_ids": ["C000003"], "time_range": "old"}
        result = expand(citation, self.source, padding=1)
        self.assertEqual(result["quote"], "2 3 4")
        self.assertEqual((result["start"], result["end"]), (5, 13))
        self.assertEqual(result["time_range"], "00:00:05–00:00:13")
        self.assertTrue(result["url"].endswith("&t=5s"))
        self.assertEqual(result["retrieved_segment_ids"], ["C000003"])
        self.assertEqual(citation["time_range"], "old")

    def test_context_expansion_stops_at_source_edges(self):
        citation = {"source_id": "video", "segment_ids": ["C000000"]}
        result = expand(citation, self.source)
        self.assertEqual(result["segment_ids"], [f"C{i:06}" for i in range(5)])


if __name__ == "__main__":
    unittest.main()
