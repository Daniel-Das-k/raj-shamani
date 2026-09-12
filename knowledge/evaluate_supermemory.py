"""Bounded live retrieval audit of the existing caption trial (no remote writes).

Run with ``python -m knowledge.evaluate_supermemory``. Calls three document status
endpoints and eight searches by default. --cases selects a JSON question set.
Saves raw evidence locally; does not score semantic
correctness or claim that caption timing matches the audio.
"""
from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import time

from .ingest import read_json, write_json
from .supermemory import ROOT, TRIAL, Supermemory
from .supermemory_captions import CONTAINER, resolve_hit


CASES = [
    ("sleep_en", "What does Andrew Huberman say about sleep and mental performance?", "Y566_T-YlNQ"),
    ("sleep_hi", "एंड्रयू ह्यूबरमैन के अनुसार नींद मानसिक प्रदर्शन को कैसे प्रभावित करती है?", "Y566_T-YlNQ"),
    ("career_hinglish", "Career mein growth ruk gayi hai, khud ko improve karne ke liye kya karna chahiye?", "XwawXRaNfzM"),
    ("focus_en", "What does Dr Sahar Yousef explain about task switching and its effect on focus?", "4Vz6L8B73i4"),
    ("named_unfiltered", "What does Andrew Huberman say about sleep and mental performance?", None),
    ("broad", "Across these videos, what advice is given about improving work performance?", None),
    ("unrelated", "What PostgreSQL commands configure streaming replication between two database servers?", None),
    ("false_premise", "What is the exact seven-digit password Andrew Huberman gives for his private sleep app?", "Y566_T-YlNQ"),
]


def score_anchors(case, citations, sources):
    """Measure coverage of preselected passages, not semantic answer accuracy."""
    rows = []
    for group in case.get("gold_groups", []):
        segments = sources[group["video_id"]]["segments"]
        positions = {s["id"]: i for i, s in enumerate(segments)}
        start, end = positions[group["start_segment"]], positions[group["end_segment"]]
        if start > end:
            raise ValueError("Reversed reference passage.")
        expected = {s["id"] for s in segments[start:end + 1]}
        def coverage(limit):
            found = {sid for c in citations[:limit] if c["source_id"] == group["video_id"]
                     for sid in c["segment_ids"]}
            return round(len(expected & found) / len(expected), 3)
        rows.append({**group, "top1_coverage": coverage(1), "top3_coverage": coverage(3),
                     "all_coverage": coverage(len(citations))})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, help="JSON questions with optional reference segment spans")
    args = parser.parse_args()
    cases = read_json(args.cases) if args.cases else [
        {"id": case_id, "query": query, "video_id": video_id} for case_id, query, video_id in CASES]
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    directory = TRIAL / "timed-captions"
    manifest = read_json(directory / "manifest.json")
    if manifest["container"] != CONTAINER:
        raise ValueError("Unexpected trial container.")
    sources = {video_id: read_json(directory / f"{video_id}-{record['revision'][:12]}.json")
               for video_id, record in manifest["sources"].items()}
    if not isinstance(cases, list) or not 1 <= len(cases) <= 30:
        raise ValueError("Supply 1–30 question cases.")
    for case in cases:
        if not isinstance(case.get("query"), str) or not case["query"].strip():
            raise ValueError("Each case needs a query.")
        if not isinstance(case.get("id"), str) or not case["id"].replace("_", "").isalnum():
            raise ValueError("Case IDs must contain letters, digits or underscores.")
        if case.get("video_id") and case["video_id"] not in sources:
            raise ValueError("Unknown video filter.")
        score_anchors(case, [], sources)  # Validate references before making API calls.
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Case IDs must be unique.")
    started = datetime.now(timezone.utc)
    output = TRIAL / "evaluations" / started.strftime("%Y%m%dT%H%M%S%fZ")
    output.mkdir(parents=True)
    report = {"started_at": started.isoformat(), "container": CONTAINER,
              "scope": "retrieval only; no generated answers or audio verification",
              "status": [], "cases": []}
    client = Supermemory(CONTAINER)
    try:
        for video_id, record in manifest["sources"].items():
            state = client.document(record["document_id"]).get("status")
            report["status"].append({"video_id": video_id, "status": state})
            print(json.dumps({"video_id": video_id, "status": state}), flush=True)
        for case in cases:
            case_id, query, video_id = case["id"], case["query"], case.get("video_id")
            before = time.monotonic()
            row = {**case, "video_filter": video_id}
            try:
                filters = {"AND": [{"key": "video_id", "value": video_id}]} if video_id else None
                raw = client.search(query, limit=8, filters=filters)
                write_json(output / (case_id + "-raw.json"), raw)
                row["request_seconds"] = round(time.monotonic() - before, 3)
                hits = raw.get("results", [])
                citations, seen = [], set()
                for hit in hits:
                    matched = (hit.get("metadata") or {}).get("video_id")
                    if matched not in sources or (video_id and matched != video_id):
                        continue
                    for citation in resolve_hit(hit, sources[matched]):
                        key = (matched, tuple(citation["segment_ids"]))
                        if key not in seen:
                            citations.append(citation)
                            seen.add(key)
                row.update(retrieved_chunks=len(hits), citations=citations,
                           anchor_coverage=score_anchors(case, citations, sources),
                           provider_source_ids=sorted({str((h.get("metadata") or {}).get("video_id")) for h in hits}))
                print(json.dumps({"id": case_id, "seconds": row["request_seconds"],
                                  "chunks": len(hits), "citations": len(citations),
                                  "anchor_coverage": [g["all_coverage"] for g in row["anchor_coverage"]],
                                  "sources": row["provider_source_ids"]}), flush=True)
            except (RuntimeError, ValueError, OSError) as exc:
                row.update(error=str(exc), request_seconds=round(time.monotonic() - before, 3))
                print(json.dumps({"id": case_id, "error": str(exc)}), flush=True)
            report["cases"].append(row)
            write_json(output / "results.json", report)
    finally:
        client.session.close()
        write_json(output / "results.json", report)
    print("Evidence: " + str(output / "results.json"), flush=True)
    return int(any("error" in row for row in report["cases"]))


if __name__ == "__main__":
    raise SystemExit(main())
