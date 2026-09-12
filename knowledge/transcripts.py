"""Source identity and immutable, word-timed evidence. No provider dependencies."""
from __future__ import annotations

import hashlib
import json
import math
import re
from urllib.parse import parse_qs, urlparse


def youtube_source(url: str) -> dict:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    parts = parsed.path.strip("/").split("/")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Supply a full YouTube video URL.")
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parts[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        video_id = (parse_qs(parsed.query).get("v", [""])[0] if parsed.path == "/watch"
                    else parts[1] if len(parts) == 2 and parts[0] in {"shorts", "live", "embed"} else "")
    else:
        raise ValueError("This first version supports YouTube video links.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("The link must identify a single YouTube video.")
    return {"id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}"}


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def timestamp(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"


def deepgram_words(raw: dict) -> list[dict]:
    try:
        words = raw["results"]["channels"][0]["alternatives"][0]["words"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Missing Deepgram word timestamps.") from exc
    if not words:
        raise ValueError("No speech was transcribed; nothing to index.")
    output = []
    for index, word in enumerate(words):
        start, end = float(word["start"]), float(word["end"])
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
            raise ValueError("Invalid transcript word timestamps.")
        if output and start < output[-1]["start"]:
            raise ValueError("Transcript words must be ordered by start time.")
        text = word.get("punctuated_word") or word.get("word")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Transcript contains an empty word.")
        reasons = []
        if word.get("speaker") is None:
            reasons.append("speaker unassigned")
        for field in ("confidence", "speaker_confidence"):
            confidence = word.get(field)
            if confidence is not None and (not math.isfinite(float(confidence)) or not 0 <= float(confidence) <= 1):
                raise ValueError(f"Invalid {field}.")
            if confidence is not None and float(confidence) < 0.7:
                reasons.append(f"low {field}")
        if output and start < output[-1]["end"]:
            reasons.append("overlapping word timestamps")
        output.append({"index": index, "start": start, "end": end, "text": text.strip(),
                       "language": word.get("language"),
                       "speaker": word.get("speaker"), "confidence": word.get("confidence"),
                       "speaker_confidence": word.get("speaker_confidence"), "review_reasons": reasons})
    return output


def chunk_words(source_id: str, words: list[dict], revision: str) -> list[dict]:
    """Keep nearby dialogue together, retaining overlap and original word positions."""
    chunks = []
    first = 0
    while first < len(words):
        last = first + 1
        while last < len(words):
            previous, current = words[last - 1], words[last]
            duration = previous["end"] - words[first]["start"]
            if last - first >= 100 or current["end"] - words[first]["start"] > 45:
                break
            if current["start"] - previous["end"] > 2:
                break
            if duration >= 25 and previous["text"].endswith((".", "?", "!", "।")):
                break
            last += 1
        selected = words[first:last]
        chunks.append({"id": f"{source_id}:{revision[:16]}:{first}-{last - 1}",
                       "source_id": source_id, "start": selected[0]["start"],
                       "end": max(w["end"] for w in selected), "words": selected,
                       "text": " ".join(w["text"] for w in selected)})
        if last == len(words):
            break
        # Avoid repeatedly emitting tiny chunks when a long silence caused a split.
        silence = words[last]["start"] - words[last - 1]["end"] > 2
        first = last if silence else max(first + 1, last - min(12, (last - first) // 4))
    return chunks


def citation(chunk: dict, first: int, last: int) -> dict:
    if type(first) is not int or type(last) is not int or first > last:
        raise ValueError("Citation word positions must be an ordered integer range.")
    selected = [w for w in chunk["words"] if first <= w["index"] <= last]
    if len(selected) != last - first + 1 or any(w["index"] != first + i for i, w in enumerate(selected)):
        raise ValueError("Citation refers to words outside the retrieved passage.")
    source = youtube_source(chunk["url"])
    start, end = selected[0]["start"], max(w["end"] for w in selected)
    return {"chunk_id": chunk["id"], "source_id": source["id"], "title": chunk["title"],
            "video_url": source["url"], "start_word": first, "end_word": last,
            "url": f"{source['url']}&t={math.floor(start)}s", "start": start, "end": end,
            "time_range": f"{timestamp(start)}–{timestamp(end)}",
            "quote": " ".join(w["text"] for w in selected),
            "detected_languages": sorted({w["language"] for w in selected if w.get("language")}),
            "speakers": sorted({str(w["speaker"]) if w["speaker"] is not None else "unassigned" for w in selected}),
            "human_verified": False,
            "review_reasons": sorted({reason for w in selected for reason in w["review_reasons"]})}
