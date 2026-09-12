# Supermemory deployment assessment — 12 September 2026

Update after this assessment: all three keys are now configured; a separate caption
answer CLI was implemented and exercised. The configured Llama model was unavailable
to the account, so the answer experiment used GPT-OSS 120B as an explicit override.
See [the subsequent question-and-answer review](VIDEO_QA_REVIEW.md) and
[actual replies](VIDEO_QA_ACTUAL_ANSWERS.md). The configuration and test counts below
describe the earlier assessment. The browser now supports persistent channel imports
and caption-based answers; see [channel import details](CHANNEL_IMPORT.md).
The configured model has also been updated to the tested GPT-OSS model.
Production readiness work remains open.

**Decision: suitable for continued development of this video knowledge base;
not ready to deploy the current application to production.** The live experiment
demonstrates useful retrieval with traceable caption citations. It does not establish
perfect answers, audio-accurate timestamps, or production reliability.

## What was checked

- Read the Supermemory client, caption ingestion/resolution, server, and answer
  pipeline; checked configuration and current dependencies without printing secrets.
- Made three live document-status requests and eight live search requests against
  the existing caption collection. No documents were uploaded, changed, or deleted.
- Re-ran all 44 Python tests and both JavaScript UI smoke tests: all passed.
  These include mocked providers and DOM behavior, not a live browser-to-Supermemory
  answer test. `git diff --check` also passed.
- Independently reconstructed every returned citation from its saved segment IDs,
  checking exact quote text, start/end times, and the canonical timestamped URL.
- Reviewed retrieved excerpts for the cases below. This is a small diagnostic sample,
  not a labeled accuracy benchmark or a load test.

## Live results

All three caption documents still report `done`, covering 12,558 saved segments.
Eight searches completed successfully. Observed client request latency was
0.624–1.410 seconds, median 1.063 seconds, excluding any answer generation.

| Case | Citation ranges | Finding |
| --- | ---: | --- |
| English: Huberman, sleep and mental performance; video filter | 8 | Relevant discussion at 23:10–24:06; opening teaser ranked first. |
| Hindi: equivalent sleep question; video filter | 8 | Retrieved the same relevant discussion; shows cross-language retrieval in this example. |
| Hinglish: stalled career growth; CTO video filter | 8 | Relevant self-investment discussion at 43:39–44:39. |
| English: Sahar Yousef, task switching; video filter | 8 | Relevant explanation of time/energy costs at 1:11:52–1:12:39. |
| Huberman sleep question without a video filter | 8 | Also returned Sahar Yousef excerpts; naming a person in the query does not enforce source scope. |
| Work-performance advice across videos | 8 | Included all three videos; this does not prove comprehensive coverage. |
| Unrelated PostgreSQL replication question | 0 | No matches in this example. |
| Fabricated premise: Huberman's exact seven-digit sleep-app password | 8 | Returned sleep excerpts, none supporting a password answer. A valid citation alone cannot establish answerability. |

All **56/56 citation ranges matched the saved caption text and timing records**.
This is an integrity result, not 100% answer accuracy. Seventeen ranges shared at
least one segment with an earlier range within the same query. Opening teasers,
overlaps, and mid-sentence boundaries reduce result usefulness.

Example video links:

- [Huberman, sleep and performance — 23:10](https://www.youtube.com/watch?v=Y566_T-YlNQ&t=1390s)
- [Sauvik Banerjjee, investing in yourself — 43:39](https://www.youtube.com/watch?v=XwawXRaNfzM&t=2619s)
- [Sahar Yousef, task switching — 1:11:52](https://www.youtube.com/watch?v=4Vz6L8B73i4&t=4312s)

No listening review or playback verification was performed. These are automatic
caption boundaries, with original transcription errors preserved. Speaker identity
within each excerpt is not established by the video's title.

## Storage and retrieval design

The trial uploads marked transcript text using `taskType: "superrag"`. It searches
document chunks through `/v4/search` with `searchMode: "documents"`, reranking enabled,
and aggregation disabled. This is managed RAG; the implementation does not depend on
a knowledge graph of extracted facts. This matches the documented
[SuperRAG use case](https://supermemory.ai/docs/concepts/super-rag) and
[document search mode](https://supermemory.ai/docs/api-reference/recall-search/search-memory-entries).

Supermemory holds the searchable copy. Local revisioned JSON holds the canonical
caption text, segment IDs, video identity, and timing. Retrieved text must match
those records before the application builds a timestamped link. Deployments must
persist and back up those records and their manifest; having only the API key and
remote documents is insufficient for this resolver.

The earlier direct YouTube-URL experiment failed for all three videos. Caption-text
ingestion succeeded. Those earlier URL failures were not re-submitted in this audit;
see [the original trial](SUPERMEMORY_TRIAL.md).

## Release blockers and required changes

| Priority | Evidence in current code/configuration | Required before release |
| --- | --- | --- |
| Blocker | `knowledge/server.py` calls the local `Store`/embedding pipeline. Its SQLite database has zero sources. Supermemory exists only in separate CLI commands. | Connect browser search, source status, and ingestion to one selected backend. |
| Blocker | `knowledge/supermemory_captions.py` returns excerpts, with no generated-answer or semantic-support check. The existing `knowledge/answers.py` expects word-indexed local passages. | Adapt answer generation and verification to caption evidence; derive every link/time locally; withhold unsupported answers. Test the fabricated-premise case end to end. |
| Blocker | `GROQ_API_KEY` is absent; the current environment also lacks `groq` and `sentence_transformers`. | Configure and install the chosen answer provider. A Supermemory-only retrieval backend can avoid the local embedding dependency. |
| Blocker for public hosting | Server binds to loopback and rejects external hosts; uses Python `http.server`. No user authentication or application rate limiting is implemented. | Use a production server/deployment configuration, HTTPS, appropriate access controls, and usage limits. Python itself [does not recommend `http.server` for production](https://docs.python.org/3/library/http.server.html). |
| Blocker for reliable ingestion | API client has no retries/backoff; jobs are daemon threads with in-memory state; ingestion holds the same lock as queries. | Add durable jobs, bounded retry/backoff for transient failures, and separate ingestion from serving queries. |
| Blocker for recoverable data | Canonical records and manifest are local ignored files. JSON writes share fixed temporary filenames. A changed revision creates a new remote document without retiring the old one; unchanged uploads skip without checking remote health. | Persist and back up canonical data; serialize or transact writes; reconcile document status, failed uploads, and obsolete revisions. |
| Quality gate | Named queries leak across videos without explicit filters; retrieved excerpts may be irrelevant, overlapping, or teasers. | Resolve source scope, improve excerpt selection, and evaluate relevance/abstention on a labeled English/Hindi/Hinglish question set. |
| Timing gate | Only caption-record integrity was checked. No audio comparison. | Listen to representative clips and measure timing/text accuracy; use better transcription/alignment where captions are inadequate. Deepgram is optional for the caption path. |

The current keys are sufficient for the tested retrieval experiment. They are not
sufficient for the existing answer generator. No end-to-end generated answers,
high-concurrency behavior, restart recovery, production cost, or large-library recall
were validated. Those limitations prevent a production readiness claim even though
the small retrieval trial worked.

## Reproduce and inspect

```bash
.venv/bin/python -m knowledge.evaluate_supermemory
.venv/bin/python -m unittest discover -s tests -q
node --test tests/web_smoke.cjs
```

The evaluation script performs only the three status checks and eight searches above;
it saves evidence under a new UTC-stamped directory and does not mutate remote data.
Its successful exit indicates successful API calls, not semantic correctness.

Evidence from this audit:
`data/supermemory-trial/evaluations/20260912T092457663132Z/results.json`, plus the
adjacent per-query raw responses. Query text and original excerpts are stored locally
in that ignored directory. This assessment added the evaluation script and this report;
it did not change the application backend or deploy a service.
