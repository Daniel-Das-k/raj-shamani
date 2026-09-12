"""Offline retrieval experiments; never modifies production search behavior."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import statistics

from .evaluate_supermemory import score_anchors
from .ingest import read_json, write_json
from .supermemory import TRIAL
from .supermemory_captions import resolve_hit
from .transcripts import timestamp


def expand(citation, source, padding=12):
    """Read neighboring original segments, explicitly retaining their provenance."""
    segments = source["segments"]
    positions = {s["id"]: i for i, s in enumerate(segments)}
    start = max(0, positions[citation["segment_ids"][0]] - padding)
    end = min(len(segments), positions[citation["segment_ids"][-1]] + padding + 1)
    selected = segments[start:end]
    start_time, end_time = selected[0]["start"], max(s["end"] for s in selected)
    return {**citation, "segment_ids": [s["id"] for s in selected],
            "quote": " ".join(s["text"] for s in selected),
            "start": start_time, "end": end_time,
            "time_range": f"{timestamp(start_time)}–{timestamp(end_time)}",
            "url": source["url"] + f"&t={math.floor(start_time)}s",
            "retrieved_segment_ids": citation["segment_ids"],
            "context_added_locally": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    report = read_json(args.results)
    directory = TRIAL / "timed-captions"
    manifest = read_json(directory / "manifest.json")
    sources = {v: read_json(directory / f"{v}-{r['revision'][:12]}.json")
               for v, r in manifest["sources"].items()}
    count, overlap, rows = 0, 0, []
    for case in report["cases"]:
        if "error" in case:
            continue
        seen = set()
        for citation in case["citations"]:
            source = sources[citation["source_id"]]
            segments = {s["id"]: s for s in source["segments"]}
            selected = [segments[sid] for sid in citation["segment_ids"]]
            valid = (citation["quote"] == " ".join(s["text"] for s in selected)
                     and citation["start"] == selected[0]["start"]
                     and citation["end"] == max(s["end"] for s in selected)
                     and citation["url"] == source["url"] + f"&t={math.floor(selected[0]['start'])}s")
            if not valid:
                raise ValueError("Citation integrity mismatch: " + case["id"])
            count += 1
            keys = {(source["id"], sid) for sid in citation["segment_ids"]}
            overlap += bool(seen & keys)
            seen.update(keys)
        raw = read_json(args.results.parent / (case["id"] + "-raw.json"))
        reordered, used = [], set()
        for hit in sorted(raw["results"], key=lambda h: h.get("similarity", 0), reverse=True):
            video_id = (hit.get("metadata") or {}).get("video_id")
            if video_id not in sources or (case.get("video_filter") and video_id != case["video_filter"]):
                continue
            for c in resolve_hit(hit, sources[video_id]):
                key = (video_id, tuple(c["segment_ids"]))
                if key not in used:
                    reordered.append(c)
                    used.add(key)
        variants = {"baseline": case["citations"], "similarity_order": reordered,
                    "neighbor_context": [expand(c, sources[c["source_id"]]) for c in case["citations"]],
                    "similarity_and_context": [expand(c, sources[c["source_id"]]) for c in reordered]}
        row = {"id": case["id"], "variants": {name: {
            "anchors": score_anchors(case, cites, sources),
            "excerpt_words": sum(len(c["quote"].split()) for c in cites)} for name, cites in variants.items()}}
        rows.append(row)
        print(case["id"], {name: [(a["top1_coverage"], a["all_coverage"]) for a in result["anchors"]]
                           for name, result in row["variants"].items()})
    seconds = [c["request_seconds"] for c in report["cases"] if "error" not in c]
    result = {"source_results": str(args.results), "validated_citations": count,
              "overlapping_ranges": overlap, "median_request_seconds": statistics.median(seconds),
              "min_request_seconds": min(seconds), "max_request_seconds": max(seconds),
              "note": "Anchor coverage is not semantic accuracy; extra context adds words and may add noise.",
              "cases": rows}
    write_json(args.results.parent / "offline-analysis.json", result)
    print({k: v for k, v in result.items() if k != "cases"})


if __name__ == "__main__":
    main()
