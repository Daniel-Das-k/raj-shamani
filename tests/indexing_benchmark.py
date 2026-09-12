"""Opt-in live benchmark: adds one video to a running library and records readiness.

python tests/indexing_benchmark.py VIDEO_ID [--port 8765] [--timeout 300]
The video remains in the library. No channel-wide import or answer call is made.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time

import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_id")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", args.video_id):
        parser.error("Invalid video ID")
    base = f"http://127.0.0.1:{args.port}"
    with requests.Session() as session:
        def request(path, data=None):
            response = session.get(base + path, timeout=30) if data is None else session.post(base + path, json=data, timeout=30)
            response.raise_for_status()
            return response.json()
        # This small-library benchmark intentionally refuses a large catalog.
        initial = request("/api/status")
        if initial["total"] > 50 or any(s["id"] == args.video_id for s in initial["sources"]):
            parser.error("Choose a new video in a library of at most 50 videos")
        if any(c["state"] in {"queued", "scanning"} for c in initial["channels"]) or any(initial["counts"].get(s) for s in ("queued", "processing", "indexing")):
            parser.error("Wait until the existing import queue is idle")
        started = time.monotonic()
        result = {"video_id": args.video_id, "started_at": datetime.now(timezone.utc).isoformat(), "transitions": []}
        request("/api/ingest", {"urls": ["https://www.youtube.com/watch?v=" + args.video_id]})
        previous = None
        while time.monotonic() - started < args.timeout:
            status = request("/api/status")
            video = next((v for v in status["sources"] if v["id"] == args.video_id), None)
            state = video["state"] if video else "queued"
            if state != previous:
                transition = {"state": state, "elapsed_seconds": round(time.monotonic() - started, 2)}
                result["transitions"].append(transition)
                print(json.dumps(transition), flush=True)
                previous = state
            if state in {"ready", "error", "skipped"}:
                break
            time.sleep(2)
        result.update(status=previous, elapsed_seconds=round(time.monotonic() - started, 2), poll_interval_seconds=2)
        directory = Path("data/indexing-benchmarks")
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{args.video_id}.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
        return 0 if previous == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
