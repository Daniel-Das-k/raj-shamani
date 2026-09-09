"""Groq transcription + local, audio-based pyannote speaker attribution.

Run stages individually; successful raw results are reused to avoid repeat charges.
Speaker names are assigned only after human verification of the clip.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"
DEFAULT_URL = "https://youtube.com/shorts/mX9pVUXsFJk"


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def configure():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT.parent / ".env")
    OUT.mkdir(exist_ok=True)
    os.environ.setdefault("HF_HOME", str(ROOT / "cache" / "huggingface"))
    os.environ.setdefault("TORCH_HOME", str(ROOT / "cache" / "torch"))
    os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")


def require_key(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing {name}; add it to the local .env file. Never paste it into logs.")
    return value


def prepare(url):
    audio = ROOT / "audio.wav"
    if audio.exists():
        with wave.open(str(audio)) as stream:
            if stream.getnframes() == 0 or stream.getframerate() != 16000:
                raise RuntimeError("Existing audio is invalid. Inspect it before retrying.")
        source_path = OUT / "source.json"
        if source_path.exists() and read_json(source_path).get("url") != url:
            raise RuntimeError("Existing audio belongs to another URL. Move it to a new test folder before continuing.")
        print("Reusing extracted audio.")
        return
    subprocess.run([
        sys.executable, "-m", "yt_dlp", "--no-playlist", "--write-info-json",
        "-f", "bestaudio/best", "-o", str(ROOT / "source.%(ext)s"), url,
    ], check=True)
    candidates = [p for p in ROOT.glob("source.*") if p.suffix in {".webm", ".m4a", ".mp4", ".ogg", ".opus"}]
    if len(candidates) != 1:
        raise RuntimeError("Expected one downloaded media file; inspect source files.")
    subprocess.run([
        "ffmpeg", "-nostdin", "-n", "-i", str(candidates[0]), "-vn",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio),
    ], check=True)
    with wave.open(str(audio)) as stream:
        duration = stream.getnframes() / stream.getframerate()
    write_json(OUT / "source.json", {
        "url": url, "duration_seconds": duration,
        "timestamp_origin": "start of supplied Shorts clip, NOT the full podcast",
    })


def transcribe():
    path = OUT / "groq_raw.json"
    if path.exists():
        print("Reusing saved Groq response.")
        return
    from groq import Groq
    key = require_key("GROQ_API_KEY")
    started = time.perf_counter()
    with Groq(api_key=key, max_retries=0, timeout=120) as client:
        with (ROOT / "audio.wav").open("rb") as audio:
            result = client.audio.transcriptions.create(
                file=audio, model="whisper-large-v3",
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"], temperature=0,
                # Detect language; use transcription, never translation.
            )
    write_json(path, result.model_dump(mode="json"))
    write_json(OUT / "transcription_run.json", {
        "provider": "Groq", "model": "whisper-large-v3",
        "elapsed_seconds": time.perf_counter() - started,
        "language_setting": "automatic", "human_verified": False,
    })
    print("Saved Groq transcript and timestamps. Not yet human verified.")


def diarize(num_speakers=None):
    path = OUT / ("speakers_raw.json" if num_speakers is None else f"speakers_forced_{num_speakers}.json")
    if path.exists():
        print("Reusing saved speaker turns.")
        return
    token = require_key("HF_TOKEN")
    import numpy as np
    import torch
    from pyannote.audio import Pipeline
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    started = time.perf_counter()
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-community-1", token=token,
    )
    # Decode PCM ourselves to avoid platform-specific audio decoder dependencies.
    with wave.open(str(ROOT / "audio.wav")) as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 16000):
            raise RuntimeError("Audio must be mono 16-bit PCM at 16 kHz.")
        data = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(np.float32) / 32768
    inference_started = time.perf_counter()
    count_options = {"min_speakers": 1, "max_speakers": 3} if num_speakers is None else {"num_speakers": num_speakers}
    result = pipeline({"waveform": torch.from_numpy(data).unsqueeze(0), "sample_rate": 16000}, **count_options)

    def rows(annotation):
        return [{"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)}
                for turn, _, speaker in annotation.itertracks(yield_label=True)]

    write_json(path, {
        "model": "pyannote/speaker-diarization-community-1",
        "device": "cpu", "speaker_count_setting": "automatic within 1 to 3" if num_speakers is None else f"forced {num_speakers}; diagnostic only",
        "elapsed_seconds": time.perf_counter() - started,
        "inference_seconds": time.perf_counter() - inference_started,
        "regular": rows(result.speaker_diarization),
        "exclusive": rows(result.exclusive_speaker_diarization),
        "human_verified": False,
    })
    print("Saved audio-based speaker turns. Identity labels still need human review.")


def overlap(a, b):
    return max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))


def attribute_words(words, exclusive, regular):
    output = []
    for word in words:
        start, end = float(word["start"]), float(word["end"])
        if end < start:
            raise ValueError("Reversed word timestamps")
        item = {"start": start, "end": end, "text": word["word"].strip()}
        scores = {}
        for turn in exclusive:
            scores[turn["speaker"]] = scores.get(turn["speaker"], 0) + overlap(item, turn)
        ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
        coverage = ranked[0][1] / (end - start) if ranked and end > start else 0
        item["speaker"] = ranked[0][0] if ranked and ranked[0][1] > 0 else "UNASSIGNED"
        competing = len(ranked) > 1 and ranked[1][1] > 0
        active = [turn for turn in regular if overlap(item, turn) > 0]
        simultaneous = any(a["speaker"] != b["speaker"] and overlap(
            {"start": max(start, a["start"]), "end": min(end, a["end"])}, b
        ) > 0 for i, a in enumerate(active) for b in active[i+1:])
        item["review_reasons"] = []
        if coverage < 0.6:
            item["review_reasons"].append("weak timing overlap")
        if competing:
            item["review_reasons"].append("word spans speaker boundary")
        if simultaneous:
            item["review_reasons"].append("simultaneous speech")
        if output and start < output[-1]["end"]:
            item["review_reasons"].append("overlapping ASR word timestamps")
        output.append(item)
    return output


def timestamp(seconds):
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def merge(num_speakers=None):
    raw = read_json(OUT / "groq_raw.json")
    speakers = read_json(OUT / ("speakers_raw.json" if num_speakers is None else f"speakers_forced_{num_speakers}.json"))
    export_dir = OUT if num_speakers is None else OUT / f"forced_{num_speakers}"
    export_dir.mkdir(exist_ok=True)
    if not raw.get("words"):
        raise RuntimeError("Groq did not return word timestamps; cannot attribute transcript reliably.")
    words = attribute_words(raw["words"], speakers["exclusive"], speakers["regular"])
    mapping_path = ROOT / "speaker_names.json"
    names = read_json(mapping_path) if mapping_path.exists() else {}
    # Only a manually verified mapping may replace anonymous speaker labels.
    groups = []
    for word in words:
        if not groups or word["speaker"] != groups[-1]["speaker"] or word["start"] - groups[-1]["end"] > 1 or word["end"] - groups[-1]["start"] > 8:
            groups.append({"speaker": word["speaker"], "start": word["start"], "end": word["end"], "words": []})
        groups[-1]["words"].append(word)
        groups[-1]["end"] = max(groups[-1]["end"], word["end"])
    for group in groups:
        group["name"] = names.get(group["speaker"], group["speaker"])
        group["text"] = " ".join(w["text"] for w in group["words"])
        group["review_reasons"] = sorted({r for w in group["words"] for r in w["review_reasons"]})
    write_json(export_dir / "speaker_transcript.json", {"human_verified": False, "timestamp_origin": "clip", "speaker_count_setting": speakers['speaker_count_setting'], "turns": groups})
    with (export_dir / "speaker_transcript.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["start_seconds", "end_seconds", "speaker", "text", "review_reasons"])
        for group in groups:
            writer.writerow([group["start"], group["end"], group["name"], group["text"], "; ".join(group["review_reasons"])])
    subtitles = [f"{i}\n{timestamp(g['start'])} --> {timestamp(g['end'])}\n{g['name']}: {g['text']}\n"
                 for i, g in enumerate(groups, 1)]
    (export_dir / "speaker_transcript.srt").write_text("\n".join(subtitles), encoding="utf-8")
    for index, label in enumerate(sorted({g["speaker"] for g in groups}), 1):
        selected = [g for g in groups if g["speaker"] == label]
        lines = [f"[{timestamp(g['start'])} - {timestamp(g['end'])}] {g['name']}: {g['text']}" for g in selected]
        (export_dir / f"speaker_{index}.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"Exported {len(groups)} turns. Check overlaps and speaker identities against the clip.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "transcribe", "diarize", "merge", "all"])
    parser.add_argument("--url", default=os.getenv("SOURCE_URL", DEFAULT_URL), help="YouTube URL used by the prepare stage")
    parser.add_argument("--speakers", type=int, choices=[1, 2, 3], help="Separate diagnostic output with forced speaker count")
    args = parser.parse_args()
    configure()
    stages = {"prepare": prepare, "transcribe": transcribe, "diarize": diarize, "merge": merge}
    for name, action in stages.items():
        if args.stage in ("all", name):
            if name == "prepare":
                action(args.url)
            elif name in ("diarize", "merge"):
                action(args.speakers)
            else:
                action()


if __name__ == "__main__":
    main()
