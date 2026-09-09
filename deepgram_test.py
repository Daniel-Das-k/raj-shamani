"""Test Deepgram diarization and align its speakers to the saved Groq words."""
from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs" / "deepgram"
OUT.mkdir(parents=True, exist_ok=True)


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def overlap(a, b):
    return max(0.0, min(float(a["end"]), float(b["end"])) - max(float(a["start"]), float(b["start"])))


def choose_speaker(word, reference_words):
    matches = [(overlap(word, other), other) for other in reference_words]
    matches.sort(key=lambda item: item[0], reverse=True)
    if matches and matches[0][0] > 0:
        return matches[0][1], "time_overlap"
    midpoint = (float(word["start"]) + float(word["end"])) / 2
    nearest = min(reference_words, key=lambda other: abs(midpoint - (float(other["start"]) + float(other["end"])) / 2))
    distance = abs(midpoint - (float(nearest["start"]) + float(nearest["end"])) / 2)
    return (nearest, "nearest_within_0.6s") if distance <= 0.6 else (None, "unassigned")


def main():
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT.parent / ".env")
    key = os.getenv("DEEPGRAM_API_KEY")
    if not key:
        raise RuntimeError("Missing DEEPGRAM_API_KEY")

    raw_path = OUT / "raw.json"
    if raw_path.exists():
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        elapsed = None
    else:
        params = {
            "model": "nova-3",
            "language": "multi",
            "diarize_model": "latest",
            "utterances": "true",
            "smart_format": "true",
        }
        started = time.perf_counter()
        with (ROOT / "audio.wav").open("rb") as audio:
            response = requests.post(
                "https://api.deepgram.com/v1/listen",
                params=params,
                headers={"Authorization": f"Token {key}", "Content-Type": "audio/wav"},
                data=audio,
                timeout=180,
            )
        response.raise_for_status()
        elapsed = time.perf_counter() - started
        raw = response.json()
        dump("raw.json", raw)

    alternative = raw["results"]["channels"][0]["alternatives"][0]
    dg_words = alternative.get("words", [])
    if not dg_words or any("speaker" not in word for word in dg_words):
        raise RuntimeError("Deepgram did not return word-level speaker labels")

    groq = json.loads((ROOT / "outputs" / "groq_raw.json").read_text(encoding="utf-8"))
    aligned = []
    for word in groq["words"]:
        match, method = choose_speaker(word, dg_words)
        aligned.append({
            "start": float(word["start"]),
            "end": float(word["end"]),
            "text": word["word"].strip(),
            "speaker": None if match is None else int(match["speaker"]),
            "speaker_confidence": None if match is None else match.get("speaker_confidence"),
            "alignment": method,
        })

    turns = []
    for word in aligned:
        if not turns or word["speaker"] != turns[-1]["speaker"] or word["start"] - turns[-1]["end"] > 1 or word["end"] - turns[-1]["start"] > 8:
            turns.append({"speaker": word["speaker"], "start": word["start"], "end": word["end"], "words": []})
        turns[-1]["words"].append(word)
        turns[-1]["end"] = max(turns[-1]["end"], word["end"])
    for turn in turns:
        turn["text"] = " ".join(word["text"] for word in turn["words"])

    speakers = sorted({int(word["speaker"]) for word in dg_words})
    summary = {
        "provider": "Deepgram",
        "model": "nova-3",
        "language": "multi",
        "diarization_model": "latest",
        "request_seconds": elapsed,
        "detected_speakers": speakers,
        "speaker_count": len(speakers),
        "deepgram_word_count": len(dg_words),
        "groq_word_count": len(groq["words"]),
        "deepgram_transcript": alternative.get("transcript", ""),
        "speaker_names_verified": False,
        "timestamp_origin": "supplied 45-second clip",
    }
    dump("summary.json", summary)
    dump("groq_words_with_deepgram_speakers.json", aligned)
    dump("groq_turns_with_deepgram_speakers.json", turns)

    with (OUT / "speaker_turns.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["start_seconds", "end_seconds", "speaker", "groq_text"])
        for turn in turns:
            writer.writerow([turn["start"], turn["end"], turn["speaker"], turn["text"]])

    lines = [
        "# Deepgram speaker test", "",
        f"Detected speakers: {len(speakers)} ({', '.join(map(str, speakers))})",
        f"Request time: {elapsed:.2f} seconds" if elapsed is not None else "Reused saved response",
        "Speaker identities are not yet verified.", "",
    ]
    for turn in turns:
        lines.extend([f"**{turn['start']:.2f}–{turn['end']:.2f}s · Speaker {turn['speaker']}**", "", turn["text"], ""])
    (OUT / "result.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ["request_seconds", "speaker_count", "detected_speakers", "deepgram_word_count", "groq_word_count"]}, indent=2))


if __name__ == "__main__":
    main()
