# Knowledge Retriever: Podcast Transcript Pilot

An experimental pipeline for building searchable podcast datasets with:

- Hindi-English transcription and word timestamps
- speaker diarization (who spoke when)
- speaker-attributed transcript exports
- raw result preservation for human review

The pilot compares three approaches:

1. Groq Whisper large-v3 for transcription plus local pyannote Community-1.
2. Groq Whisper large-v3 words aligned to Deepgram speaker timestamps.
3. Deepgram Nova-3 multilingual for both transcription and diarization.

The 45-second trial favored Deepgram alone. It finished in 6.63 seconds,
captured 135 words, and detected the brief opening speaker. Groq captured 123
words and missed that opening question. Deepgram also made one suspicious late
speaker switch, so human review remains required.

## Setup

Requirements:

- Python 3.12+
- FFmpeg on `PATH`
- Groq, Deepgram, and Hugging Face tokens as needed
- accepted access to `pyannote/speaker-diarization-community-1`

Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Add credentials to `.env`. Never commit that file.

## Groq and local speaker separation

```powershell
.venv\Scripts\python.exe run_test.py prepare --url "YOUTUBE_URL"
.venv\Scripts\python.exe run_test.py transcribe
.venv\Scripts\python.exe run_test.py diarize
.venv\Scripts\python.exe run_test.py merge
python export_speaker_review.py
```

The speaker model runs on CPU by default. A forced speaker count is available
only as a diagnostic:

```powershell
.venv\Scripts\python.exe run_test.py diarize --speakers 2
.venv\Scripts\python.exe run_test.py merge --speakers 2
python export_speaker_review.py --speakers 2
```

A forced count is an assumption, not evidence that the labels are correct.

## Deepgram

After audio preparation:

```powershell
.venv\Scripts\python.exe deepgram_test.py
```

This uses Nova-3 multilingual, the latest batch diarizer, word timestamps,
utterances, and smart formatting. It saves Deepgram's native transcript and a
diagnostic alignment of Groq words to Deepgram speaker timestamps.

For the pilot clip, Deepgram's native transcript was better than the combined
output because Groq omitted the opening question. The current direction is
Deepgram-first, with Groq retained as an optional check for uncertain passages.

## Data rules

- Store original wording, timestamps, confidence, and anonymous speaker labels.
- Add verified speaker names only after listening or matching a known voice.
- Keep a separate normalized English translation for search.
- Preserve raw provider responses so corrections remain auditable.
- Flag overlaps, short interjections, and uncertain speaker boundaries.
- Keep downloaded media and generated transcripts outside Git.

## Limitations

- Speaker labels are anonymous until verified.
- Short replies, cross-talk, music, and edited clips can cause false switches.
- Provider utterance labels may disagree with word-level labels.
- This pilot validates dataset capture; it is not yet a searchable knowledge base.

References:

- [Groq speech-to-text](https://console.groq.com/docs/speech-to-text)
- [Deepgram diarization](https://developers.deepgram.com/docs/diarization/)
- [Deepgram multilingual code switching](https://developers.deepgram.com/docs/multilingual-code-switching)
- [pyannote Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
