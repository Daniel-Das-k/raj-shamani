# Knowledge Retriever

## Figuring Out reader

The browser now opens an editorial discovery experience with real episodes from
the committed `INDEXED_VIDEOS.md` snapshot. It includes topic and title search,
episode playback, and named collections stored in this browser's local storage.
The snapshot is a browsing catalog; it does not mark any video as searchable.
Original captions and provider configuration are still required for checked answers.

When connected, questions use `POST /api/ask/stream`. The server sends original
retrieved excerpts before the final checked answer, using newline-delimited JSON.
Interim excerpts are explicitly labelled as awaiting relevance checks. The final
response uses the existing evidence-verification pipeline and is saved to response
history. The JSON `/api/ask` endpoint remains available. A remote Supermemory search
failure falls back to local keyword retrieval when the original captions exist.

The answer view includes an adjacent source player, original-caption disclosure,
timestamp links, and saved moments. Playback uses YouTube; individual videos may
have embedding or availability restrictions. Collections are local to the browser,
while past questions remain in `data/responses.sqlite3`.

UI assets: `knowledge/web/index.html`, `reader.css`, `reader.js`, `catalog.json`.
Asset provenance is in `knowledge/web/MEDIA.md`. The previous browser script and
styles remain in the repository for the historical regression suite.

### Verify the reader

With the local Python server running and Google Chrome installed:

```bash
npm ci
npm run test:reader
python -m unittest discover -s tests -p 'test_*.py'
```

Set `APP_URL` for a different local server URL or `CHROME_PATH` for another Chrome
executable. The browser check uses an isolated browser context, real catalog data,
and simulated provider responses; it never makes a paid answer request. Screenshots
are saved under `data/reader-check/`. `npm test` runs the earlier browser-script
regressions. Live answer accuracy and latency require the original dataset and keys.

The Python server serves both the frontend and API at http://127.0.0.1:8000;
start it with `.venv/bin/python -m knowledge serve`. No separate frontend server
or API URL configuration is needed. With the archive and keys available, run
`npm run test:reader:live` for an opt-in browser check using one real question
and the configured paid providers. It checks the streamed answer, citations,
and reopening backend history without another generation request. The exact
response and a screenshot are saved in `data/reader-live-check/`.

---

Find useful moments in Raj Shamani's indexed videos. Describe a question or situation
and get one concise reply based on the retrieved passages, followed by summaries of
useful video moments, their relevance and limitations, and timestamp links to watch.
Supported advice addresses the reader directly; missing facts and personal outcomes
are not filled in from general model knowledge.

For example: "What do the videos say about customer validation?" or "Where is work
stress discussed?" Suggestions distinguish direct discussion from related background.
When no direct answer is found in the retrieved excerpts, useful related clips may
still be shown. If no useful related answer passes review, the reader returns the
closest verified excerpt summary with a clear notice that a direct answer was not
found and a specific explanation of what the excerpt does not provide. This closest
content is background, even when its connection is weak; missing answer details are
never invented. Ambiguous
questions can receive a clarification. Generated answers, summaries, limitations,
clarifications, and interface messages are always in English, even when the question
uses or requests another language. Original transcript quotes stay unchanged in the
expandable evidence section. Caption interpretation and answer quality still have limits.

## Run the knowledge base

The browser uses **YouTube captions + Supermemory retrieval + OpenAI video guidance**.
The default browser is a fixed **Raj Shamani** library. It lists only his already
indexed videos and lets readers ask across them or select one video. Channel handles,
video URLs, import actions, pending videos, and background indexing are disabled.
The existing 50-video collection is preserved; no re-indexing is required.

On macOS/Linux with Python 3.12+:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-channels.txt
# First setup only: copy .env.example to .env, preserving any existing keys.
# Set SUPERMEMORY_API_KEY and OPENAI_API_KEY (optional OPENAI_CHAT_MODEL).
python -m knowledge serve
```

Open http://127.0.0.1:8000 and ask a question. The sidebar shows the indexed video
catalog; recommendations include summaries, relevance explanations, limitations,
expandable original captions and timestamp links. Descriptions and their checks use
`OPENAI_CHAT_MODEL=gpt-4.1-mini` by default.
The OpenAI API account needs its own available quota; Supermemory credits are separate. FFmpeg, Deepgram, and local embeddings are unnecessary
for this caption-based browser.

The catalog and queue persist in `data/channels.sqlite3`. Original timed captions
persist under `data/supermemory-trial/timed-captions/`; Supermemory stores searchable
text with video IDs and revision metadata. This is retrieval-augmented generation
(RAG), with no application-managed graph database. Back up the entire data directory.
The reader does not adopt new trial documents or start an import worker. A fresh
checkout needs the existing local data directory and access to the corresponding
Supermemory container; indexed data and credentials are not committed to Git.

Pending, failed, and unindexed videos are excluded from the reader catalog. There is no automatic paid audio
transcription fallback. Only provider-completed documents become searchable.
Caption timestamps are machine-generated segment boundaries, not verified audio
alignment. Answers still need evaluation; citation validation cannot guarantee
that the model interprets a quote correctly.

See [channel import details](CHANNEL_IMPORT.md), the earlier
[question-and-answer review](VIDEO_QA_REVIEW.md), and
[actual generated replies](VIDEO_QA_ACTUAL_ANSWERS.md).
This remains a local single-user app, without public hosting or authentication.

## Retrieval and answer reliability

The reader combines Supermemory semantic search with keyword search over the existing
saved captions, using up to two query reformulations and relevance selection. It keeps
nearby transcript context and preserves canonical timestamp links. Each of up to six
passages is summarized without the user question. A separate selection step sees the
question and these fixed summaries, then adds a relevance explanation and scope limit.
A separate review checks each proposed card against its own original excerpt and can
downgrade a direct match to related, or reject it. Up to three checked, nonredundant
moments are shown. A synthesis step combines their original passages into one concise
reply and checks every sentence against its own cited excerpts. Unsupported sentences
can be removed while keeping independently checked advice. A separate scope check
validates what the reply says the retrieved passages do not establish. Partial replies
name the missing part. One repair is allowed; if synthesis cannot be verified or its
provider fails, the checked moments remain available without an unchecked answer.
When no ordinary card passes, a fallback ranks the available summaries by proximity
to the question and independently checks up to three candidates until one passes.
Its checked summary and missing-information statement form the reply, with
`coverage` and `reply_coverage` set to `closest` and a timestamp citation. The same
fallback reuses a checked related card when the reply writer finds no substantive
answer to synthesize. Search
includes a broader subject query and retains nearest candidates when ranking finds
no direct answer. Empty retrieval or failed source checks can still prevent a reply;
the fallback does not establish that the entire index was exhaustively checked.
See [the consolidated reply check](CONSOLIDATED_REPLY_REVIEW.md).
A model check can still miss semantic mistakes or overstate how useful a clip is.
See [the workflow and limits](CHANNEL_IMPORT.md).

The [15-question English system check](ENGLISH_15_QUERY_SYSTEM_CHECK.md) records the
current closest-content workflow: 11 substantive replies, 3 closest-content replies,
and 1 clarification, with no request errors. All displayed citations matched saved
captions, but assistant review found six responses needing quality revisions. The
report includes every exact reply, reference, limitation, and reproduction command.

The tester's 15 questions are in `tests/fixtures/direct_query_review.json`. Run the
opt-in paired evaluation with `.venv/bin/python tests/evaluate_direct_queries.py`.
It uses the configured OpenAI/Supermemory keys and incurs API usage, but never imports
videos. It compares the baseline at `fe4048a` against the revised pipeline and saves
full results locally in `data/accuracy-review/video_guide-results.json`. Existing results
are reused; use a new output filename for a fresh run. A verifier pass is not an
independent accuracy score; review claims and summaries against their original captions.
See [the measured results and remaining accuracy gaps](ACCURACY_IMPROVEMENTS.md).
The [new 15-question review](WIDE_QUERY_REVIEW.md) includes every recorded reply,
reference links, an assessment of the evidence, and prioritized improvements. Questions
with missing topics or unnamed options now ask for clarification before retrieval.
The earlier [response improvement report](RESPONSE_IMPROVEMENTS.md) preserves the same
15 questions and their exact before/after replies, reference summaries and timestamp links.
All development runs, including unsuccessful approaches, remain under `data/accuracy-review/`.
Normal app questions and replies continue to be saved in `data/responses.sqlite3` and can
be reopened through Saved responses without making another answer request.
The default evaluation strategy, `video_guide`, matches the reader. `isolated_statements`
preserves the previous direct-answer workflow; `isolated_summaries` is another experiment.
See [the video guide review](VIDEO_GUIDE_REVIEW.md) for saved questions and recommendations.

## Separate local transcription backend

The original CLI commands below use Deepgram and local hybrid retrieval. Their
database is separate from the channel browser. Use `serve --backend local` to open
that collection. The channel import implementation remains in `ChannelLibrary` for maintenance;
the default server uses `RajShamaniLibrary` and rejects import API requests.

Python 3.12+ and FFmpeg are required. From this directory on macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-app.txt
cp .env.example .env
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell and use
`Copy-Item .env.example .env`. Set `DEEPGRAM_API_KEY` and `OPENAI_API_KEY` in `.env`.
OpenAI is used for understanding questions and generating answers; the new pipeline
does not require Groq transcription or pyannote. `HF_TOKEN` is only needed for
the separate original pyannote experiment below.

```bash
# Add one or several links. Each command processes the whole linked video.
python -m knowledge ingest "YOUTUBE_URL_1" "YOUTUBE_URL_2"

# Process every video listed in LINKS.md.
python -m knowledge ingest --links-file LINKS.md

# Open http://127.0.0.1:8000 for the browser interface.
# The Process videos button also ingests the links in LINKS.md.
python -m knowledge serve --backend local

# Inspect the collection and search original passages.
python -m knowledge sources
python -m knowledge search "customer validation before building features"

# Ask a question, optionally including English translations of the excerpts.
python -m knowledge ask "What do the videos say about customer validation?" --translate

# Structured output, also returned by POST /api/ask with {"question": "..."}.
python -m knowledge ask "Where do the videos discuss distractions?" --json
```

Ingestion downloads media, sends audio to Deepgram, and creates embeddings locally.
Questions send the question, source catalog, and retrieved transcript passages to OpenAI. These
provider calls use your accounts. The first nonempty ingestion/search loads the
public embedding model from Hugging Face; subsequent runs reuse its local cache.
`sources` and empty-collection queries need no API keys or model downloads.

The CLI is stateless: after a clarification, submit a question containing both the
original question and the missing detail. Every browser submission is an independent query containing only the current input.
After a clarification, rewrite the complete question with the missing detail; previous
questions and saved responses are never automatically added to a new request. Browser requests are now recorded in `data/responses.sqlite3` and
available under **Saved responses**, with View response and Download JSON controls.
Each record includes the question, selected video, final answer or safe error, exact
citation data, model, timestamp, and elapsed time. Recording starts with new requests;
earlier unsaved browser answers cannot be reconstructed. Reopening a saved response
does not call the model again. This is an answer archive, not conversation memory.

An answered result contains `points`, each with `text` and `citations`. Every citation
includes the video title, `source_id`, canonical `video_url`, timestamped `url`, precise
`start` and `end` seconds, readable `time_range`, original `quote`, and original word
positions. Other statuses are `needs_clarification`, `insufficient_evidence`, and
`invalid_evidence`, with empty `points`. This replaces the earlier advice-only `steps`
response shape. The browser displays the same data and can play the excerpt in place.

## Supermemory trial

The optional trial uses Supermemory's `taskType: "superrag"` and v4 search with
`searchMode: "documents"`. The live text control was retrievable through v4, while
v3 returned no matches for the same indexed content; `search --v3` remains available
for comparison.
It needs only `SUPERMEMORY_API_KEY` in `.env` and the lightweight dependencies below;
it does not download a local embedding model or require Deepgram/Groq.

```bash
python -m pip install -r requirements-supermemory.txt
python -m knowledge.supermemory check
python -m knowledge.supermemory add --links-file LINKS.md
python -m knowledge.supermemory status
python -m knowledge.supermemory search "What do the videos say about customer validation?"
```

The three URLs are submitted for Supermemory's own extraction. A `queued` response
only means accepted, not searchable. Run `status` again to inspect processing; `done`
means the provider reports indexing complete. Search returns the provider's excerpts,
not generated advice. Run `python -m knowledge.supermemory control` to submit/check
a small synthetic text control in a separate container, useful for distinguishing
general indexing delays from video-specific extraction problems.

Video trial documents are isolated under `knowledge-retriever-trial`; the control
uses `knowledge-retriever-trial-control`. Stable IDs and a local manifest avoid repeat
uploads. Raw extraction responses and the latest search are saved under
`data/supermemory-trial/`. Documents remain in the Supermemory account for inspection.

This direct-URL trial does not supply the channel browser's citations or insert unverified
provider excerpts into the timed transcript database. Timestamp-looking strings in
provider output are diagnostic only, not validated word alignment. Direct video
extraction must be evaluated before it can supply precise citations. Our existing
Deepgram pipeline and answer generation still need their own provider keys.

### Working caption-based trial

In the live trial, direct extraction of all three YouTube URLs failed. Downloading
their original automatic captions and uploading the transcript text succeeded:
all three caption documents reached `done`, and real questions returned passages.
The default browser now uses this caption retrieval approach, with a persistent
channel catalog and OpenAI answer generation. These commands remain useful for diagnostics.

```bash
# Needs yt-dlp as well as requirements-supermemory.txt. Downloads captions only.
python -m yt_dlp --skip-download --write-auto-subs --sub-langs '.*-orig' --sub-format json3 --write-info-json --paths data/supermemory-trial/captions --output '%(id)s.%(ext)s' 'YOUTUBE_URL'

# Upload all downloaded original caption files, retaining local timing records.
python -m knowledge.supermemory_captions upload
python -m knowledge.supermemory_captions status
python -m knowledge.supermemory_captions search "What do the videos say about sleep?"
python -m knowledge.supermemory_captions search "Why do professionals stop growing in their careers?" --video-id XwawXRaNfzM
```

Supermemory stores and searches the caption text, with stable segment markers.
The original text and times remain under `data/supermemory-trial/timed-captions/`.
Only complete retrieved segments matching the saved original text, video ID, and
revision produce citations. Partial segments, invented IDs, altered wording, and
stale revisions are rejected. Links are constructed from the saved caption times.
The `--video-id` option applies both a provider metadata filter and a local check.

These are automatic **caption-segment** timestamps, not verified word-level audio
alignment. This trial returns retrieved excerpts rather than generated answers.
It does not need Deepgram, Groq, or a local embedding model. OpenAI is needed
for the app's answer-generation pipeline; Deepgram remains useful when captions
are missing or when a separate transcription is required. This small trial establishes
working retrieval, not a full quality comparison with the local retrieval backend.

API references: [SuperRAG](https://supermemory.ai/docs/concepts/super-rag),
[add document](https://supermemory.ai/docs/api-reference/ingest/add-document), and
[document search](https://supermemory.ai/docs/api-reference/documents/search-documents).

## How evidence reaches an answer in the local transcription backend

1. **Capture:** Deepgram Nova-3 multilingual produces original words, confidence,
   timestamps, and anonymous speaker labels. Raw responses are retained.
2. **Index:** overlapping passages preserve nearby dialogue. Each word keeps its
   original episode-relative position and time. No English translation overwrites
   the original transcript.
3. **Retrieve:** multilingual E5 embeddings find related meaning across languages;
   SQLite full-text search contributes keyword matches. Rankings are combined.
   Query planning expands the question into related terms and can select explicitly
   named videos. Comparison/overview searches spread candidates across videos.
4. **Answer:** OpenAI assesses candidates and writes a direct reply in short paragraphs,
   preserving qualifications and differing perspectives. Each reference has a brief
   summary, with the unchanged original transcript available to expand in the browser.
5. **Cite:** the model selects stored passage IDs and word ranges. Python validates
   those ranges and constructs quotes, time ranges, and YouTube links from source
   data. Invented passage IDs and out-of-range citations are rejected.
6. **Check support:** a separate OpenAI call checks every answer paragraph and reference
   summary against its own cited original excerpts. Shared excerpts are sent once to
   reduce token usage. Missing, malformed, or negative checks withhold the answer.
7. **Translate:** optional English translations are cached separately from the
   original evidence. A translation failure still leaves the original answer usable.

YouTube links jump to the start of the cited excerpt, rounded down to a whole
second. Displayed start/end values retain transcript precision in JSON. Times
refer to the **linked video**, so a Short's timestamps are relative to that Short,
not an unknown full episode. Incoming `t` parameters do not crop ingestion.

The new code is in `knowledge/`. Episodes and raw responses are separated under
`data/sources/VIDEO_ID/`; the SQLite collection lives at `data/knowledge.sqlite3`.
Use `python -m knowledge --data-dir /path/to/collection ...` for another collection.
Generated data and model caches are excluded from Git.

API response caches include an audio hash and request settings. Re-running ingestion
reuses matching responses and skips unchanged embeddings; replacing an episode's
index happens in one database transaction. A failed replacement leaves its previous
searchable version intact. Source media remains on disk for review.

## Local transcription backend limits and validation

This is a local CLI and browser demo, with background ingestion in the server process.
There are no accounts or conversation memory. Browser response history is saved locally.
Keep the server running
while processing; restarting it loses job progress, but ingestion can reuse saved audio
and transcription responses. Ingestion, search, and answering share a runtime lock,
so questions may wait while a video is being processed.

Only individual YouTube video URLs are accepted; add multiple URLs to `LINKS.md`
or the ingest command. The browser also accepts individual links. Successful additions
remain in the database, but do not rewrite `LINKS.md`.
Some videos may require additional yt-dlp setup or may be unavailable to download.
Vector search scans the local collection, which is intended for an initial small
library rather than a large hosted service. Long model inputs can be truncated by
the embedding model; retrieval quality still needs evaluation on real Hindi-English
episodes and representative questions. Ordinary questions retrieve up to 12 passages;
overviews/comparisons retrieve up to 20. All indexed videos are searchable, but an
answer is based on retrieved excerpts, not an exhaustive analysis of every video.
The index captures speech, not information visible only in slides or video frames.

Citation validation proves that an excerpt and its timestamps exist in the retrieved
transcript. It does **not** prove that the model's interpretation is correct or that
ASR captured the audio perfectly. The additional support check is also model-based,
so it reduces unchecked claims without guaranteeing interpretation accuracy.
Human listening checks remain necessary, particularly
around negations, interjections, and speaker changes. No speaker names are inferred.
The backend reports machine transcripts and translations as unverified. A correction
workflow remains future work; translated excerpts are currently for display, not indexing.

Offline tests use synthetic transcripts, embeddings, and model responses. They test
source isolation, cache reuse, index replacement, retrieval wiring, clarification,
abstention, general Q&A, per-video search, cross-video citations, support-check rejection,
Hindi keyword handling, translation caching, and exact citation construction without
network access or API charges:

```bash
python -m unittest discover -s tests -v
# Optional browser-script checks with Node.js 18+ (no npm dependencies).
node --test tests/web_smoke.cjs
```

Provider integration references: [Deepgram diarization](https://developers.deepgram.com/docs/diarization/),
[OpenAI structured output](https://developers.openai.com/api/docs/guides/structured-outputs),
[multilingual E5 model](https://huggingface.co/intfloat/multilingual-e5-small),
and [yt-dlp embedding examples](https://github.com/yt-dlp/yt-dlp#embedding-examples).

## Original podcast transcript pilot

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
