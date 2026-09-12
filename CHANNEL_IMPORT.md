# Channel library

The default `python -m knowledge serve` now opens the Supermemory caption library.
The previous Deepgram/local-embedding browser remains available with `--backend local`.

## User flow

1. Enter `@rajshamani` or a supported YouTube channel URL and click Find.
2. Review the resolved channel and sample titles, then click Import long-form videos.
3. Regular uploads from the Videos tab are discovered and queued, excluding Shorts.
   The worker saves timed captions locally,
   submits the text to Supermemory, and polls until indexing completes.
4. Ask across ready videos or select one video. Answers include original excerpts,
   start/end times, and links to the supporting moments.

Pause takes effect between discovery items or video operations. Resume keeps saved
progress; rescanning deduplicates by YouTube video ID. Retry issues retries skipped
or failed items. A known failed remote document is checked again, rather than blindly
uploaded a second time. Check for new videos queues a rescan; automatic checks run
every six hours while the process is running. There is no background OS scheduler.

## Storage and retrieval

- `data/channels.sqlite3`: channels, membership, per-video state, retries, remote
  document IDs, caption revisions, and synchronization times. SQLite WAL transactions
  persist work. An exclusive worker lock prevents two servers processing one library.
- `data/supermemory-trial/timed-captions/`: canonical text, segment IDs, and original
  caption times, saved before upload. Pending files support retries after network loss.
- Supermemory container `knowledge-retriever-caption-trial`: transcript documents
  with stable custom IDs and video/revision metadata. Existing trial videos are adopted.
- Retrieval uses Supermemory document search. Python rejects unknown videos, stale
  revisions, altered text, and invalid segment IDs before building citations.
- Groq generates an answer from retrieved evidence; a second model call checks support.
  The browser cites complete retrieved passages to retain nearby qualifications.

This is RAG. The application does not create or query a graph database. It retains
caption text and references; it does not archive YouTube media. Back up the entire
data directory and retain access to the Supermemory account. A custom local data
directory does not create a separate remote tenant/container.

## Limits

Only public, accessible uploads exposed in the Videos tab can be discovered. The
separate Shorts and Live tabs are not scanned. Short classification uses YouTube's
tab/metadata and Shorts URLs, not a guessed duration cutoff. Individual Shorts URLs
are rejected before queueing; Shorts submitted through watch links are skipped before
captions are fetched. Regular short-duration videos can still appear in the Videos tab.
This excludes the Shorts format, not every potentially repeated clip.
Captionless,
restricted, and upcoming/live videos may need attention. Transcripts over 1 MB need
splitting, which is not yet automated. Deepgram is not called as a fallback by this
worker. YouTube/provider limits can delay imports; no full-channel throughput claim
has been established. Remote indexing that stays pending continues to be polled.

Each answer searches up to eight remote results; broad questions are not an exhaustive
review of every video. Native captions can contain recognition errors. Exact quote
and timestamp validation proves provenance, not factual or interpretive correctness.
Cross-language recall and answer quality still need broader evaluation.

The server binds to loopback and has no user accounts. Public deployment still needs
authentication, per-user isolation, managed worker execution, operational monitoring,
and a larger quality/load evaluation. The worker lock currently requires macOS/Linux.

## Saved responses

New answers address the reader directly in short, grammatically complete paragraphs,
without routine narration such as “the episode says.” Predictions stay conditional and
suggestions do not become promises. Attribution remains appropriate for who-said questions
and differing perspectives.
The frontend displays the entire reply first, followed by **References**, with numbered
links connecting each paragraph to its evidence. Identical references are displayed
once. Each new reference includes a brief summary of its particular timestamped passage.
References display a labeled **Summary** first. **Show original excerpt** expands the
unchanged captions, including disfluencies and recognition errors. The control changes
to **Hide original excerpt** while expanded. Timestamp links and excerpt playback remain
available when collapsed.
The existing generation call produces both reply and summaries; no extra rewrite call is
added. The existing verification call separately checks each paragraph and each distinct
summary against its own evidence. Any rejected or missing verification check withholds
the answer. This uses additional tokens, but no additional provider requests.
Reopening an old recording uses the new layout but preserves its originally saved wording.
Older references without summaries still offer the expandable original transcript.
New reference summaries state the substance directly in one or two short sentences,
without “He tells…” or “The speaker says…” narration. Simple answers prefer a single
combined paragraph. On request, the approved billionaire example was saved as an
editorial revision (`94d9e6d8bd7b4fafb1029a357c96011f`), with the original recording
preserved. Its reply and both summaries passed the existing evidence verifier; original
captions, timestamps and links were retained. The record identifies its editorial origin
and verification model separately from generated answers.

The direct-reply browser check for “can u tell me the how to become billionaire” returned
two short paragraphs and two reference summaries, saved as
`d0d4f98f5b514721ae65845e68a3510f` (7.214 seconds). Desktop/mobile layout, collapsed and
expanded original transcripts, unchanged links/quotes, saved-response reload, and paused
indexing passed. One earlier attempt hit the provider's token limit; another exposed
remaining source narration. The final prompt was tightened and verification now sends
each original excerpt once, sharing its ID across paragraph and summary checks.
This sample is a format regression check, not a claim of perfect answer accuracy.
Offline validation passed 83 Python tests and eight frontend checks. Reproduce with
`node tests/channel_browser.cjs --direct-reply` using the Playwright setup below.
Artifacts are under `data/ui-checks/direct-reply-*`.

The revised shopping-question browser check returned one prose paragraph followed by
three references, saved as response `96c7285ec82e4a54b6364bd1f793fc58` (11.11 seconds).
Desktop/mobile rendering, original quote preservation, history reload, and the indexing
pause were verified. Two earlier live attempts were withheld by validation; the later
success does not establish a guaranteed pass rate or solve all interpretation errors.
Offline validation passed 80 Python tests and seven frontend checks. Reproduce the
live layout check with `node tests/channel_browser.cjs --shopping-reply` using the
Playwright setup documented below. Artifacts are under `data/ui-checks/shopping-reply-*`
and `data/ui-checks/polished-shopping-answer.json`.

New browser `/api/ask` requests automatically save their final response or safe error
to `data/responses.sqlite3`. **Saved responses** shows the question, time, and outcome;
View response reopens the saved answer and Download JSON exports its full record.
History is paginated in groups of 20 and persists across restarts. Opening recordings
does not regenerate answers or resume indexing. Old browser replies are not backfilled.

Records contain the selected video ID, backend/model, elapsed time, full response,
and citations with original quotes, video URLs, and start/end times. Provider failures
include their HTTP status and numeric retry interval where available, but no raw
provider headers or error bodies. Configured API keys are redacted before storage.
The response archive contains the final withheld-answer response for failed evidence
checks. Rejected drafts and verification diagnostics are saved separately under
`data/response-diagnostics/` for local debugging, with configured keys redacted; those
drafts are never displayed as answers. A history storage failure leaves the generated
answer usable and shows a warning.
The history contains local questions and answers and is excluded from Git with `data/`.

Verified with 79 Python tests, six frontend smoke checks, and a live Chrome check:
one real answered response was stored, fetched as JSON, and reopened after reload.
The channel remained paused. Reproduce with
`NODE_PATH=/private/tmp/knowledge-ui-check/node_modules node tests/channel_browser.cjs --record-response`.
This optional check makes one live answer request; it records provider errors too.

## Verification

Offline checks: `python -m unittest discover -s tests -v` and
`node --test tests/web_smoke.cjs`. Channel tests cover deduplication, restart recovery,
pause/resume, partial discovery, caption failures, lost upload responses, and source
isolation. Browser-script checks cover preview/import and the video selection payload.

Live read-only discovery resolved `@rajshamani` to
`UCzwCEE_PchiBULMnAJqhGVg`. The uploads sample included Shorts and full episodes.
Live caption extraction for `Y566_T-YlNQ` returned 4,680 `en-orig` segments.
These checks did not start a full-channel import.

A full uploads-list scan on 12 September 2026 initially found **2,553 distinct
uploads** including Shorts. After changing to long-form discovery, a new scan found
**607 uploads in the Videos tab**. These are discovery counts, not caption-availability
or successful-indexing counts. The application currently has no video-count quota.
`python -m knowledge.youtube_channels @rajshamani --count-uploads` now repeats the
long-form-only read-only count. The frontend's **Your videos** list appears above channel
discovery, with Indexed, Pending, and Needs attention filters and 50-row pagination.

The real Chrome check passed at desktop (1440 px) and mobile (390 px) widths with
no page JavaScript errors and no horizontal overflow on mobile. All three existing
videos were ready. The live question "What does the CTO say about taking responsibility
for outcomes?" returned one answer point with two citations at 00:56:19–00:57:32 and
00:59:07–01:00:02 in `XwawXRaNfzM`. The answer and links matched the selected video;
the saved excerpts discuss business accountability and taking CXO responsibility
seriously. This is one successful end-to-end answer, not a broad accuracy score.
At this checkpoint, all 68 Python tests and four frontend smoke checks passed.

Optional real Chrome check (requires a running app and an indexed CTO trial video):

```bash
npm install --prefix /private/tmp/knowledge-ui-check playwright
NODE_PATH=/private/tmp/knowledge-ui-check/node_modules node tests/channel_browser.cjs --live-answer
```

This previews the real channel without importing it and optionally asks one live
question. Screenshots and the answer JSON are saved under `data/ui-checks/`.
Set `APP_URL` and `CHROME_PATH` to override the local URL and Chrome executable.

## Measured indexing time

On 12 September 2026, the empty-queue benchmark imported the new long-form episode
`x63HCoDfAhQ` through the real running application. Caption extraction and submission
reached `indexing` at 14.14 seconds, and the worker observed the provider's `done`
status and marked it `ready` at **32.29 seconds**. The benchmark checked local status
every two seconds; the worker first polls the provider 15 seconds after submission,
then every 30 seconds while pending. These polling intervals affect observed readiness.
The video remains in the library, bringing its indexed total to four.

Evidence: `data/indexing-benchmarks/x63HCoDfAhQ.json`. Repeat on a different new video
with `.venv/bin/python tests/indexing_benchmark.py VIDEO_ID`. This opt-in benchmark
adds that video to the real library and incurs indexing usage. It does not start a
channel import. The first readiness observation is not an independent search-quality
or audio-alignment test.

A simple sequential projection of 603 remaining videos at 32.29 seconds each is
about 5.4 hours. This is not measured channel throughput: the worker can submit other
videos while remote indexing is pending, and rate limits, missing captions, retries,
and transcript lengths change the total. No full-channel timing guarantee is established.
