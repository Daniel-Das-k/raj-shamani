"""Search original YouTube captions through SuperRAG with locally validated timing."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys

from .ingest import read_json, write_json
from .supermemory import ROOT, TRIAL, Supermemory
from .transcripts import fingerprint, timestamp, youtube_source

CONTAINER = "knowledge-retriever-caption-trial"


def caption_source(info, raw, language):
    source = youtube_source("https://youtu.be/" + info["id"])
    segments = []
    events = raw.get("events", [])
    def wording(event):
        return "".join(part.get("utf8", "") for part in event.get("segs", [])).strip()
    # Some JSON3 tracks include an incomplete duplicate followed by the same
    # caption with explicit timing. Use the timed copy, never invent its duration.
    timed = {(e.get('tStartMs'), e.get('wWinId'), wording(e)) for e in events
             if e.get('tStartMs') is not None and e.get('dDurationMs') is not None}
    for event in events:
        text = wording(event)
        if not text:
            continue
        if event.get('dDurationMs') is None:
            if (event.get('tStartMs'), event.get('wWinId'), text) in timed:
                continue
            raise ValueError('Caption duration is missing and no identical timed caption is available.')
        if event.get('tStartMs') is None:
            raise ValueError('Caption start time is missing.')
        start = float(event["tStartMs"]) / 1000
        end = start + float(event["dDurationMs"]) / 1000
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError("Invalid caption timestamps.")
        if segments and start < segments[-1]["start"]:
            raise ValueError("Captions are not ordered by time.")
        segments.append({"id": f"C{len(segments):06}", "text": text, "start": start, "end": end})
    if not segments:
        raise ValueError("No timed caption segments found.")
    return {**source, "title": info["title"], "language": language,
            "revision": fingerprint(segments), "segments": segments,
            "timestamp_kind": "youtube_caption_segment", "human_verified": False}


def upload_captions(client, directory, caption_directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest.json"
    manifest = read_json(path) if path.exists() else {"container": client.container, "sources": {}}
    if manifest["container"] != client.container:
        raise ValueError("Caption manifest belongs to another container.")
    files = sorted(caption_directory.glob("*.*-orig.json3"))
    if not files:
        raise ValueError("No original-language .json3 captions found. Download them with yt-dlp first.")
    for captions in files:
        video_id, language = captions.name[:-6].split(".", 1)
        info = read_json(caption_directory / (video_id + ".info.json"))
        source = caption_source(info, read_json(captions), language)
        if source["id"] != video_id:
            raise ValueError("Caption file and video metadata identities differ.")
        existing = manifest["sources"].get(video_id)
        if existing and existing["revision"] == source["revision"]:
            continue
        content = f"Video: {source['title']}\nOriginal automatic captions (unverified).\n\n" + "\n".join(
            f"[{segment['id']}] {segment['text']}" for segment in source["segments"])
        if len(content.encode()) > 1_000_000:
            raise ValueError(f"Captions for {video_id} exceed the trial's text upload limit.")
        custom_id = f"kr-captions-{video_id}-{source['revision'][:12]}"
        # Save the authoritative segments before uploading the searchable copy.
        write_json(directory / f"{video_id}-{source['revision'][:12]}.json", source)
        result = client.add(content, custom_id, {
            "video_id": video_id, "revision": source["revision"], "video_url": source["url"],
            "title": source["title"], "caption_language": language,
            "timestamp_kind": source["timestamp_kind"], "human_verified": False,
        })
        manifest["sources"][video_id] = {"document_id": result["id"], "revision": source["revision"],
                                          "title": source["title"], "segments": len(source["segments"])}
        write_json(path, manifest)
    return manifest


def resolve_hit(hit, source):
    """Only cite complete caption segments that match our original text exactly."""
    metadata = hit.get("metadata") or {}
    if metadata.get("video_id") != source["id"] or metadata.get("revision") != source["revision"]:
        return []
    text = hit.get("chunk") or ""
    originals = {segment["id"]: (index, segment) for index, segment in enumerate(source["segments"])}
    selected = {}
    normalize = lambda value: " ".join(value.split())
    for marker, wording in re.findall(r"\[(C\d{6})\]\s*(.*?)(?=\[C\d{6}\]|\Z)", text, re.S):
        found = originals.get(marker)
        if found and normalize(wording) == normalize(found[1]["text"]):
            selected[found[0]] = found[1]
    groups = []
    previous = -2
    for index, segment in sorted(selected.items()):
        if index != previous + 1:
            groups.append([])
        groups[-1].append(segment)
        previous = index
    citations = []
    for group in groups:
        start, end = group[0]["start"], max(segment["end"] for segment in group)
        citations.append({"source_id": source["id"], "title": source["title"], "start": start, "end": end,
                          "time_range": f"{timestamp(start)}–{timestamp(end)}",
                          "url": f"{source['url']}&t={math.floor(start)}s", "video_url": source["url"],
                          "quote": " ".join(segment["text"] for segment in group),
                          "segment_ids": [segment["id"] for segment in group],
                          "timestamp_kind": "youtube_caption_segment", "human_verified": False})
    return citations


def search_captions(client, directory, query, video_id=None):
    manifest = read_json(directory / "manifest.json")
    if video_id and video_id not in manifest["sources"]:
        raise ValueError("That video is not in the caption collection.")
    filters = {"AND": [{"key": "video_id", "value": video_id}]} if video_id else None
    raw = client.search(query, limit=8, filters=filters)
    citations = []
    seen = set()
    for hit in raw.get("results", []):
        matched_id = (hit.get("metadata") or {}).get("video_id")
        if video_id and matched_id != video_id:
            continue
        record = manifest["sources"].get(matched_id)
        if not record:
            continue
        source = read_json(directory / f"{matched_id}-{record['revision'][:12]}.json")
        for item in resolve_hit(hit, source):
            key = (item["source_id"], tuple(item["segment_ids"]))
            if key not in seen:
                citations.append(item)
                seen.add(key)
    result = {"query": query, "retrieved_chunks": len(raw.get("results", [])), "citations": citations,
              "notice": "Original automatic captions; times are caption-segment boundaries, not verified word alignment."}
    write_json(directory / "last-search-raw.json", raw)
    write_json(directory / "last-search.json", result)
    write_json(directory / ("search-" + fingerprint({"query": query, "video_id": video_id})[:12] + ".json"), result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=TRIAL / "timed-captions")
    commands = parser.add_subparsers(dest="command", required=True)
    upload = commands.add_parser("upload")
    upload.add_argument("--captions-dir", type=Path, default=TRIAL / "captions")
    commands.add_parser("status")
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--video-id", help="Restrict retrieval and citations to one indexed video")
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    client = Supermemory(CONTAINER)
    try:
        if args.command == "upload":
            result = upload_captions(client, args.data_dir, args.captions_dir)
        elif args.command == "status":
            manifest = read_json(args.data_dir / "manifest.json")
            result = [{"video_id": video_id, "title": record["title"],
                       "status": client.document(record["document_id"]).get("status")}
                      for video_id, record in manifest["sources"].items()]
            write_json(args.data_dir / "status.json", result)
        else:
            result = search_captions(client, args.data_dir, args.query, args.video_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
