"""Resumable per-video capture. Cached API responses are bound to audio and settings."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys

from .providers import require_key, transcribe
from .transcripts import chunk_words, deepgram_words, fingerprint, youtube_source

DEEPGRAM_PARAMS = {"model": "nova-3", "language": "multi", "diarize_model": "latest",
                   "utterances": "true", "smart_format": "true"}
INDEX_VERSION = 2


def links_from_file(path: Path) -> list[str]:
    urls = re.findall(r'https?://[^\s<>\)\]\"\']+', path.read_text(encoding="utf-8"))
    links = list(dict.fromkeys(youtube_source(url.rstrip(".,;"))["url"] for url in urls))
    if not links:
        raise ValueError(f"No YouTube video links were found in {path.name}.")
    return links


def write_json(path: Path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def prepare(source: dict, directory: Path, progress=None) -> tuple[Path, dict]:
    """Download the whole linked video; input URL timestamp parameters are discarded."""
    from yt_dlp import YoutubeDL
    metadata_path = directory / "source.json"
    audio = directory / "audio.flac"
    if metadata_path.exists() and audio.exists():
        metadata = read_json(metadata_path)
        if metadata["id"] == source["id"]:
            return audio, metadata
        raise ValueError("Saved audio has a different source identity.")
    options = {"format": "bestaudio/best", "noplaylist": True,
               "outtmpl": str(directory / "download.%(ext)s"), "quiet": True,
               "overwrites": False}
    if progress:
        def download_progress(event):
            if event["status"] == "downloading":
                total = event.get("total_bytes") or event.get("total_bytes_estimate")
                percent = round(100 * event.get("downloaded_bytes", 0) / total) if total else None
                progress("Downloading audio" + (f" · {min(percent, 100)}%" if percent is not None else ""))
        options["progress_hooks"] = [download_progress]
    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(source["url"], download=True)
        if not info or info.get("id") != source["id"]:
            raise ValueError("The downloaded video does not match the requested source.")
        media = Path(downloader.prepare_filename(info))
    temporary = directory / "audio.pending.flac"
    if progress:
        progress("Preparing audio")
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(media),
                    "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", str(temporary)], check=True)
    temporary.replace(audio)
    metadata = {**source, "title": info.get("title") or source["id"],
                "channel": info.get("channel"), "duration_seconds": info.get("duration"),
                "timestamp_origin": "start of linked video", "human_verified": False}
    write_json(metadata_path, metadata)
    return audio, metadata


def ingest(url: str, data_dir: Path, store, embedder, progress=None) -> dict:
    source = youtube_source(url)
    directory = data_dir / "sources" / source["id"]
    directory.mkdir(parents=True, exist_ok=True)
    print(f"Preparing {source['url']}", file=sys.stderr)
    if progress:
        progress("Downloading audio")
    audio, source = prepare(source, directory, progress=progress)
    with audio.open("rb") as stream:
        audio_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    params = {**DEEPGRAM_PARAMS, "diarize_model": os.getenv("DEEPGRAM_DIARIZER", "latest")}
    run = {"audio_sha256": audio_hash, "params": params}
    cache = directory / f"deepgram-{fingerprint(run)}.json"
    if cache.exists():
        raw = read_json(cache)["response"]
    else:
        require_key("DEEPGRAM_API_KEY")
        if progress:
            progress("Transcribing speech and speaker changes")
        print("Transcribing with Deepgram…", file=sys.stderr)
        raw = transcribe(audio, params)
        write_json(cache, {"run": run, "response": raw})
    words = deepgram_words(raw)
    revision = fingerprint({"words": words, "run": run, "index_version": INDEX_VERSION})
    source = {**source, "revision": revision, "raw_response": str(cache)}
    if store.indexed(source["id"], revision, embedder.model_name):
        return {"source": source, "status": "already_indexed"}
    chunks = chunk_words(source["id"], words, revision)
    if progress:
        progress(f"Indexing {len(chunks)} passages")
    print(f"Embedding {len(chunks)} passages…", file=sys.stderr)
    vectors = embedder.encode([c["text"] for c in chunks])
    store.replace(source, chunks, vectors, embedder.model_name)
    return {"source": source, "status": "indexed", "chunks": len(chunks)}
