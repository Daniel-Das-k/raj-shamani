# Supermemory video trial — 11 September 2026

Transcript ingestion and retrieval work with the configured Supermemory key. Direct
YouTube URL extraction failed for all three videos, so the successful path uses
YouTube's original automatic captions, uploaded as SuperRAG text documents.

## Indexed collection

| Video | Timed caption segments | Supermemory status |
| --- | ---: | --- |
| [Andrew Huberman — Daily Habits](https://www.youtube.com/watch?v=Y566_T-YlNQ) | 4,680 | done |
| [Dr Sahar Yousef — Focus and Burnout](https://www.youtube.com/watch?v=4Vz6L8B73i4) | 4,850 | done |
| [Sauvik Banerjjee — Career Growth](https://www.youtube.com/watch?v=XwawXRaNfzM) | 3,028 | done |
| Total | 12,558 | All three indexed |

## Live checks

- Authentication and search access succeeded.
- A labeled synthetic text control was ingested and retrieved via `/v4/search`
  with `searchMode: "documents"`. `/v3/search` returned no matches for that control.
- A question about Huberman, sleep, and mental performance retrieved eight chunks
  and produced eight locally validated excerpt ranges. One relevant discussion is
  [23:10–24:06](https://www.youtube.com/watch?v=Y566_T-YlNQ&t=1390s).
- A career-growth question restricted to the CTO video retrieved eight chunks and
  produced eight validated ranges, all from that video. One discussion of investing
  in oneself and expanding expertise is
  [43:39–44:39](https://www.youtube.com/watch?v=XwawXRaNfzM&t=2619s).
- Some results include opening teasers and overlapping material. These two checks
  demonstrate functioning retrieval, not a comprehensive relevance benchmark.

The unrestricted Huberman question also retrieved sleep-related passages from the
Sahar Yousef video. Use `--video-id` when the question must be confined to a specific
video. The subsequent filtered CTO test confirmed that constraint in live results.

## Citation construction

Uploaded transcript text contains stable caption-segment markers. The local source
records preserve each segment's exact original wording, start/end time, video ID,
and transcript revision. Retrieved segments must match those records before links
are constructed. The provider does not generate the citation times.

These timestamps are automatic caption boundaries. They have not been checked by
listening and are not word-level forced alignment. Original caption spelling errors
remain visible. Retrieval results are source excerpts, not generated advice or
independently verified factual statements.

## Run it

```bash
.venv/bin/python -m knowledge.supermemory_captions status
.venv/bin/python -m knowledge.supermemory_captions search "What do the videos say about sleep?"
.venv/bin/python -m knowledge.supermemory_captions search "Why do professionals stop growing in their careers?" --video-id XwawXRaNfzM
```

Search and original timing records are in `data/supermemory-trial/timed-captions/`.
The direct URL trial, synthetic control, and caption collection use separate
Supermemory containers. Their remote documents remain available for inspection.

## Remaining work and validation

The existing browser has not been switched to the caption backend. Its answer
generation still needs `GROQ_API_KEY`. The original Deepgram transcription path
still needs `DEEPGRAM_API_KEY`; neither key was needed for this caption retrieval
trial. Local embedding comparison, listening checks, and a Hindi-question benchmark
have not been performed.

All 44 Python tests passed, including rejection of altered caption text, invented
segment IDs, missing segments, wrong-video results, and stale transcript revisions.
The existing two browser-script checks also passed earlier in the trial.

API references: [SuperRAG](https://supermemory.ai/docs/concepts/super-rag),
[document ingestion](https://supermemory.ai/docs/api-reference/ingest/add-document),
[v4 search](https://supermemory.ai/docs/api-reference/recall-search/search-memory-entries).
