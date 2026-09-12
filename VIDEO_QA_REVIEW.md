# Video knowledge-base questions and retrieval review

Date: 12 September 2026. Collection: the indexed Huberman, Sahar Yousef and Sauvik
Banerjjee episodes. Reviewed the saved chapter outlines and selected original
transcript sections, then prepared reference passages before running the searches.
This is a diagnostic sample, not a review of every spoken word or a listening audit.

**Actual generated replies:** [Read the seven-question answer transcript](VIDEO_QA_ACTUAL_ANSWERS.md).
Five returned answers, and two withheld unsupported answers. Manual review still found
quality issues; the results do not establish production readiness.

## Generated-answer tests after keys were added

Supermemory, Groq and Deepgram keys are now present. The Deepgram key was not exercised
because this experiment uses existing captions. Groq's configured
`llama-3.3-70b-versatile` returned 404 errors and was absent from the account's model
list. Used an explicit `openai/gpt-oss-120b` trial override, which the account listed
and successfully served. The `.env` model setting was not rewritten.
[Groq's current model documentation](https://console.groq.com/docs/models) lists the
Llama model as Enterprise and GPT-OSS 120B as a production model; actual access was
checked with the configured account, rather than inferred from the public list.

Added a caption-answer CLI adapter that supplies original segments to the generator,
validates all cited IDs against retrieved passages, constructs times/links from local
originals, then runs an answer-support check. Reference answers and reference spans
were not included in generation or verification prompts. This uses the existing Groq
JSON client and shared verifier, but remains separate from the browser backend.

Testing uncovered and fixed a provider-format bug: the verifier prompt did not
explicitly request JSON, which Groq's JSON mode rejected. The JSON client now always
appends that instruction. The requirement is documented in
[Groq's structured-output guidance](https://console.groq.com/docs/structured-outputs).

The first completed narrow-span answer test was withheld: its claims included details
outside its selected caption span. Then tested complete selected-passage citations on
seven questions. Broader citations preserved source provenance and supplied more
context for checking, at the cost of less precise excerpt boundaries.

| Question | Final test response | Manual review |
| --- | --- | --- |
| Two-column exercise | Answered; linked 26:27–27:16 | Supported, including the monthly exercise, concerns and controllable actions. |
| Remembering podcasts | Answered; linked 1:40:14–1:41:00 | Supported self-testing and reflection. Incomplete relative to the fuller reference because retrieval omitted looking up forgotten material. |
| 3M breaks | Answered; cited names, schedule and detachment passages | Main explanation supported. Unnecessary claim that “mess” was terminology used in the interview confuses caption spelling with speech; remove that claim. |
| RACI | Answered; linked 35:39–36:37 | Acronym and project-role purpose supported. Added textbook-like definitions of who does the work/is ultimately answerable go beyond the caption's clear wording; keep the answer closer to the source. Also repeated the same full-passage citation twice. |
| Hindi 5 a.m. question | Answered in Hindi with citations | Main “not everyone” qualification and sleep priority preserved. Wording about sleeping/waking early is awkward and can confuse when someone sleeps; improve translation review. |
| Fabricated sleep-app password | Insufficient evidence, no points | Correctly withheld a password even though retrieval returned eight sleep-related excerpts. |
| Unrelated PostgreSQL question | Insufficient evidence, no points | No model call was needed because retrieval returned no excerpts. |

The automated verifier passed all five released answers, including the weaknesses
above. Therefore **5/5 verifier passes is not a 100% correctness score**. Reviewed
source comparisons remain necessary, especially for definitions, names, transcription
errors and multilingual wording. No generated comparison answer or Hinglish answer
was tested in this focused seven-question run; those were retrieval tests only.

The account reported an 8,000-token-per-minute limit. Bounded retries respected the
provider's requested waits. Answer-stage elapsed times, including waits, ranged from
4.316 to 59.518 seconds for the six cases that called the model; the no-hit case took
no model time. The first answer took 4.316 seconds without such waits. This is a
sequential batch diagnostic, not a normal-traffic latency estimate or a load test.

## Prioritized changes from the evidence

1. Separate video selection from topic wording and split comparison queries. The
   five follow-up searches below directly support trying this in the app's planner.
2. Add selected neighboring context and complete-sentence citation selection. Keep
   the strict provenance checks; avoid doubling context for every candidate.
3. Tighten answer support for definitions and caption errors. Do not complete a
   source's explanation using familiar textbook knowledge or treat ASR spelling as
   intentional speech. Add independent review cases beyond the same model's verifier.
4. Deduplicate repeated citations in the presentation while retaining evidence for
   every point. Improve Hindi grammar and temporal phrasing checks.
5. Handle provider model availability and token budgets explicitly. The observed
   account limit caused long waits even for this small batch.

Only the JSON instruction fix, diagnostic tools and caption-answer trial were added.
The query/context variants remain experiments; the other recommendations have not
been silently applied to the browser or the remote index.

## What the search tests showed

Ran **15 baseline questions and five follow-up searches** against Supermemory.
All 20 searches completed successfully. The baseline had 112 citation ranges and
the follow-ups had 31. All **143 ranges** passed independent checks against the
saved captions for exact text, start/end times and canonical video links.

Baseline search latency: 0.630–1.802 seconds, median 0.955 seconds, before answer
generation. There were 43 overlapping ranges within baseline queries, and 11 in
the follow-ups. Overlap means sharing at least one already-returned caption segment.

These tests distinguish three things: retrieval of useful material, citation
integrity, and whether a generated answer is supported. Success in one does not
establish success in the others. Automatic captions can still mishear words or
misalign speech even when all stored-record integrity checks pass.

## Questions, returned material and expected answers

The descriptions below are reviewer summaries of actual returned excerpts, not
claims that the application generated these sentences. Reference answers were
written from the local transcripts and were never sent to the answer model.

| Question | What baseline retrieval returned | Review |
| --- | --- | --- |
| What is Huberman's two-column exercise for worries? | Introductory material first; the exercise at [26:27–27:16](https://www.youtube.com/watch?v=Y566_T-YlNQ&t=1587s) second. | Can support concerns in the left column versus controllable actions in the right. Ranking needs work. |
| What should I do after listening to a podcast to remember it? | Biography first; self-testing at [1:40:14–1:41:00](https://www.youtube.com/watch?v=Y566_T-YlNQ&t=6014s) second. | Retrieved self-testing but cut off the following instruction to look up forgotten material. |
| How does Huberman physically prevent social-media use during workouts? | Biography and intro first; timed phone lockbox at [2:27:06–2:27:56](https://www.youtube.com/watch?v=Y566_T-YlNQ&t=8826s) third. | Useful evidence, spread across adjacent excerpts: separate older phone, timed lockbox, two-hour workout example. |
| What are implementation intentions, and what bedtime example does Yousef give? | Explanation and 11 p.m. alarm example first, at [27:08–28:14](https://www.youtube.com/watch?v=4Vz6L8B73i4&t=1628s). | Strong result: a concrete situation triggers a planned routine. |
| Does Yousef say everyone must wake at 5 a.m.? | A direct rejection of a universal rule first, at [2:13:02–2:13:49](https://www.youtube.com/watch?v=4Vz6L8B73i4&t=7982s). | Good alternative supporting passage; the preselected reference appears later. A reference-window score alone would underrate this result. |
| What are the three breaks, their duration/frequency, and what makes them effective? | Names of breaks first; daily minutes, weekly 2–4 hours, monthly half/full day and psychological detachment at [2:28:32–2:29:36](https://www.youtube.com/watch?v=4Vz6L8B73i4&t=8912s). | Main framework is present. The later minimum-ten-minute daily example was missed at a chunk boundary. |
| What does RACI mean in the CTO episode? | Career teaser first; full role explanation fifth, at [35:39–36:37](https://www.youtube.com/watch?v=XwawXRaNfzM&t=2139s). | Relevant material exists despite captions spelling the acronym as rei/rai/racing. Wrong leading result. |
| What is the say-do ratio, and why include date/time? | Definition first; delivery deadlines later, including [38:10–39:01](https://www.youtube.com/watch?v=XwawXRaNfzM&t=2290s). | Answer needs more than one passage: commitments versus delivery, measured against dates/times. |
| How can someone respectfully disagree with a powerful boss? | Edited teaser first; longer discussion later around [1:06:26](https://www.youtube.com/watch?v=XwawXRaNfzM&t=3986s). | Contains respectful tone and asking to present a different view. Prefer fuller context over the teaser. |
| Hindi: must everyone wake at five for good performance? | Relevant discussion first; direct “some people, not everyone” qualification second at [2:03:57](https://www.youtube.com/watch?v=4Vz6L8B73i4&t=7437s). | Cross-language retrieval worked for this question. |
| Hinglish: Huberman ka left-column/right-column exercise kya hai? | The exercise was the first result at [26:27](https://www.youtube.com/watch?v=Y566_T-YlNQ&t=1587s). | Better ordering than the English phrasing in this run. |
| Two-column question without a video filter | Intro first; correct exercise second; all results happened to be from Huberman. | This query did not show source leakage; the earlier sleep query did. Continue enforcing explicit source filters. |
| Compare Huberman on switching off worries with Yousef on restorative breaks | Sleep/relaxation material from Huberman and detachment material from Yousef; missed the reference two-column passage. | Some comparison is possible, but this query missed the selected worry-management technique. Separate searches improved coverage. |
| What is the exact seven-digit password for Huberman's private sleep app? | Eight excerpts about sleep, biography and other topics. | None supports a password answer. Search results alone must not be treated as proof that the premise is true. |
| Which PostgreSQL commands configure streaming replication? | No results. | Correct behavior is to withhold unsupported database instructions. |

## Improvements actually tested

### Resolve the video first, then search for the topic

Kept the explicit video filter and removed the speaker name from three queries.
No new facts from the reference answers were added to these query rewrites.

| Change | Before | After |
| --- | --- | --- |
| RACI question without the speaker/episode wording | Eight results; complete reference passage fifth | One result, containing the complete role explanation |
| Podcast-learning question without “According to Huberman” | Biography first; only 10 of 16 reference segments found | Self-testing first; missing recall/lookup instruction in the second result; all 16 segments found |
| Two-column question without “Andrew Huberman describes” | Intro first | Relevant exercise discussion first, with full reference coverage across the returned set |

These are manually written query experiments on a small sample. They support
testing an automatic planner that separates source selection from topic retrieval;
they do not establish that deleting names always improves retrieval.

### Search each side of a comparison separately

The original combined query missed the two-column reference. A Huberman-only search
for switching off worries and a Yousef-only search for restorative breaks recovered
both preselected reference passages. This uses two API requests and up to sixteen
candidates rather than one request and eight; extra budget is part of the tradeoff.

### Fetch nearby original caption context

An offline experiment added up to twelve original caption segments on each side of
each result. This recovered the missing podcast-learning continuation and the
minimum-ten-minute break example. It did not recover the absent comparison passage.

Across thirteen positive baseline questions, complete coverage of all preselected
reference spans increased from 10/13 to 12/13. Total excerpt words roughly doubled
from 16,090 to 32,682, so blindly expanding every candidate would add noise and model
cost. Expand selected relevant passages, then select the final supported citation.
These fractions measure reference-span coverage, not answer accuracy or recall of
all valid passages in a video.

### Evaluate ordering before replacing it

Sorting the saved results by their returned similarity score improved reference
placement for several questions, but worsened the say-do example. It did not retrieve
any additional material. Do not replace provider ordering universally based on this
experiment; evaluate relevance across a larger held-out set and keep original scores.

## Reproduction and evidence

Question fixtures: `tests/fixtures/video_questions.json` and
`tests/fixtures/video_question_experiments.json`. These preserve the exact queries,
manual reference answers and segment spans used for the diagnostic.

```bash
.venv/bin/python -m knowledge.evaluate_supermemory --cases tests/fixtures/video_questions.json
.venv/bin/python -m knowledge.evaluate_supermemory --cases tests/fixtures/video_question_experiments.json
.venv/bin/python -m knowledge.analyze_supermemory data/supermemory-trial/evaluations/20260912T094148982893Z/results.json
.venv/bin/python -m knowledge.caption_answers data/supermemory-trial/evaluations/20260912T094148982893Z/results.json --model openai/gpt-oss-120b --whole-passages --rate-limit-retries 3 --case-ids columns_en learning_en three_m_en raci_en five_am_hi fabricated_password unrelated_database
```

Baseline evidence: `data/supermemory-trial/evaluations/20260912T094148982893Z/`.
Follow-up evidence: `data/supermemory-trial/evaluations/20260912T094426709914Z/`.
Each includes results, original provider responses, and offline measurements.

The experiments did not upload, reindex or delete remote documents. The browser
backend remains separate; the new caption answer runner is a CLI test harness.

Final answer evidence: `answers-20260912T100539950779Z.json` in the baseline directory.
Earlier failed runs are retained separately; their 404, JSON-format and rate-limit
failures are not counted as successful answer tests. Local verification: 59 Python
tests and two JavaScript UI smoke tests passed; `git diff --check` passed.
