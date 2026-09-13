# Channel library

The default `python -m knowledge serve` opens a fixed Raj Shamani reader library.
Only ready videos linked to channel `UCzwCEE_PchiBULMnAJqhGVg` are returned by status,
pagination, and retrieval. Channel/video input and import controls are hidden; direct
calls to import and channel-management endpoints return HTTP 403. No worker starts,
so restarting the reader cannot resume imports. Existing queued videos and captions
are retained. Answers, reference summaries, playback, and saved responses remain available.

The import workflow below documents the retained maintenance implementation in
`ChannelLibrary`; it is no longer exposed by the default reader server.
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
- OpenAI (`gpt-4.1-mini` by default) generates an answer from retrieved evidence; a second model call checks support.
  The browser cites complete retrieved passages to retain nearby qualifications.

The Raj Shamani reader shows a consolidated reply followed by useful moments. Each excerpt is summarized without the question. A separate bridge step
selects immutable summaries and explains why each connects to the question and what
it does not establish. A separate review checks all three fields and the direct/
related classification. The original passages behind those checked cards are then
synthesized into one reply. Each substantive sentence is checked against its cited original excerpts. Unsupported
sentences may be omitted while independently checked advice is kept. A separate scope
check validates the stated limitation against the bounded set of originals; one repair
is allowed. Failure leaves the cards available.
Up to three checked moments are displayed; unrelated content
is not forced into a suggestion. Questions, cards and review decisions are retained
locally. The evaluation default `video_guide` matches the app; `isolated_statements`
preserves the previous workflow. See [the guide review](VIDEO_GUIDE_REVIEW.md).

This is RAG. The application does not create or query a graph database. It retains
caption text and references; it does not archive YouTube media. Back up the entire
data directory and retain access to the Supermemory account. A custom local data
directory does not create a separate remote tenant/container.

Answers, reference summaries, and support checks use `OPENAI_API_KEY` from `.env`.
`OPENAI_CHAT_MODEL` defaults to `gpt-4.1-mini`. The client explicitly connects to
`https://api.openai.com/v1`, so an inherited endpoint override cannot redirect the key
to another service. Planning/ranking use JSON mode; reader answers and verification use
strict JSON schemas with `store=false`. OpenAI API quota is
separate from Supermemory indexing credits; billing quota failures are distinguished
from temporary rate limits. Historical Groq evaluation scripts remain optional.
The OpenAI migration passed 98 Python tests and eight frontend checks. A live equity
ownership question passed generation and evidence verification in 9.319 seconds,
with three summarized references (record `95c9b54d70af40bfbdf5054cbd89f935`). An earlier
CXO draft exceeded the three-citations-per-paragraph limit and was withheld. This
connection check is not a broader answer-quality evaluation.

## Limits

An optional local `data/import-budget.json` enables a limited free-credit import. It
records a minimum USD balance, billing reset date, and maximum number of new document
submissions. Before every upload, the worker reads Supermemory's live billing and
auto-top-up endpoints, checks that the account is still Free with no payment method
or auto top-up, and reserves the UTF-8 payload byte count at $1/million plus $0.01 as
a conservative per-document allowance. Imports run one document at a time and wait
15 seconds after completion before the next upload to allow billing to settle.
Insufficient headroom, changed billing settings/period, an unreadable budget/balance,
or a provider error pauses channels. Stopping is persisted; Resume does not clear the
budget stop. Review credits before explicitly reconfiguring it. This is a local forecast
guard, not a provider-enforced dollar cap: asynchronous billing, other account usage,
and pricing changes can affect actual charges. It never purchases credits or changes
payment settings. See [billing API documentation](https://supermemory.ai/docs/overview/billing).

The 12 September limited run began at $3.861969 with a $0.861969 reserve (a $3 target)
and a secondary limit of 100 new submissions. Shorts remain excluded. The credit guard
and queue serialization are covered by the offline tests.

The limited batch can also contain an ordered `video_ids` snapshot and a
`target_ready_videos` count. Snapshot ordering takes precedence over retry/update times;
uploads outside the snapshot are excluded. The worker pauses once the total ready count
reaches the target. For the requested 100-video batch, the current indexed set was checked
against a fresh read of YouTube's latest 100 Videos-tab entries; a new upload and two
deferred videos were added back to the selection. This is a snapshot at the time of the
check, not a continuously changing definition of “latest.” Unavailable captions or the
credit reserve can prevent reaching the target; older uploads are not silently substituted.
The user subsequently reduced this run to the first 50 entries of that same snapshot,
with a target of 50 ready videos and the credit reserve unchanged.

Some YouTube JSON3 captions contain a durationless duplicate of an explicitly timed
entry. The parser ignores the incomplete copy only when text, start time, and caption
window match a timed copy exactly. Missing duration without such a match is rejected;
no timestamp duration is guessed. This fixes the observed FO543 caption parsing failure.

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

The reader searches the original question plus at most two short reformulations,
each with up to eight remote results. It also searches an ephemeral local SQLite FTS5
index built from the same ready videos' saved captions. This does not upload documents,
change the index state, or include pending/other-channel videos. Rank fusion combines
semantic and keyword results; overlapping windows are merged with a 150-second bound,
and nearby original segments provide context. An LLM selects at most six relevant
passages from at most 24 candidates. These searches are not an exhaustive review of
every video. Malformed planning/ranking output falls back to the original question or
validated candidates; provider errors are surfaced rather than retried indefinitely. Native captions can contain recognition errors. Exact quote
and timestamp validation proves provenance, not factual or interpretive correctness.
Cross-language recall and answer quality still need broader evaluation.

The planning step can instead return one clarifying question when the topic or
referenced options are missing. The reader then returns `needs_clarification` without
searching or generating an answer, and saves the diagnostic. The existing frontend
treats every submission as an independent query. There is no follow-up option or
automatic concatenation. After a clarification, the reader can edit the full question
and submit it again. For clearly named English
topics, a search-first guard ignores optional planner clarification and searches the
original question. Generic questions without named options can still ask for clarification;
non-English requests retain the planner's language-aware decision.
Clear factual questions and broad topic questions do not require a personal situation.

The server binds to loopback and has no user accounts. Public deployment still needs
authentication, per-user isolation, managed worker execution, operational monitoring,
and a larger quality/load evaluation. The worker lock currently requires macOS/Linux.

## Saved responses

The current guide records its consolidated reply when supported, recommended moments, summaries,
relevance explanations, limitations, and original citations. Saved recommendations
reopen without another model call. The following describes the earlier answer workflow;
previous recordings remain readable with their original wording.

### Previous answer workflow

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
Generation produces both the reply and reference summaries. Verification checks each
sentence against its own cited excerpts, with paragraph context used only to resolve
pronouns. OpenAI structured output requires a named check for every answer/summary
sentence; missing/extra checks and any unsupported sentence still fail closed. Reasons
identify unsupported claims rather than just returning a generic rejection.
Generation's schema restricts citations to retrieved passage IDs and at most three
references per paragraph. Python resolves full original segment ranges, so the model
does not need to reproduce long segment IDs. Verification selects named spans from
each item's own evidence; Python resolves the supporting words and rejects unknown or
out-of-scope spans. These checks enforce provenance and format; model judgments can
still miss a semantic error, so an approved answer is not a guarantee of accuracy.
One bounded repair can correct citation formatting, remove unsupported claims, or fix
summaries. The replacement must pass full citation validation and support verification
again. Corrupt source text/timing is never sent to a model for repair. A second failure
withholds the answer; there is no unchecked fallback or retry-until-approved loop.
A typical answered query uses four LLM calls (planning, passage selection, generation,
verification), or up to six with a repair. This trades extra latency and tokens for
retrieval coverage and complete checks; costs must include all calls.
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
checks. Every reader query's retrieval details, generated attempts, per-sentence verification
checks, and final result are saved separately under `data/response-diagnostics/` for
local debugging, with configured keys redacted. The response's `diagnostic_id` links to
that file; rejected drafts are never displayed as answers. Provider exceptions still
produce safe errors in response history and may interrupt diagnostic capture. A history storage failure leaves the generated
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
