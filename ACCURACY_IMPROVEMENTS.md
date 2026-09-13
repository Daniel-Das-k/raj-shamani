# Retrieval and answer accuracy review

13 September 2026. Existing 50 indexed Raj Shamani videos; GPT-4.1 mini remains the configured default. No videos were imported or re-indexed.

Retrieval and citation reliability improved. **Semantic accuracy still has known gaps; this is not a production-accuracy sign-off.** Returning an answer and passing a model check do not establish that every claim is faithful.

## What changed

- Search the original question and up to two reformulations, including English equivalents for Hindi/Hinglish. Combine Supermemory results with local keyword retrieval over the same ready videos.
- Merge overlapping passages and include nearby captions to retain qualifications. Select at most six passages from at most 24 candidates.
- Constrain generated citations to retrieved passage IDs. Python derives original segment ranges, timestamps and YouTube links; the model does not generate them.
- Require a separate structured check for every answer sentence and reference-summary sentence. Supporting span IDs are restricted to that item’s own evidence, and resolved back to original text.
- Allow one repair for unsupported claims or malformed output, followed by complete revalidation. A second failure still withholds the answer.
- Save retrieval choices, drafts, exact failed checks and final outcomes locally, linked to saved responses by diagnostic ID.

## Paired live comparison

The same 15 questions were run against the baseline implementation at `fe4048a` and the revised pipeline. Baseline search used the original question and eight Supermemory results. Queries were executed sequentially within each run; provider responses and generation can vary. The baseline snapshots and raw results are retained under ignored `data/accuracy-review/`.

| Measure | Tester report | Fresh baseline | Revised pipeline |
| --- | ---: | ---: | ---: |
| Answers returned | 4/15 | 2/15 | 15/15 |
| Withheld after validation | 10/15 | 12/15 | 0/15 |
| No supporting passages | 1/15 | 1/15 | 0/15 |
| Median response time | Not recorded | 5.36 s | 19.15 s |
| Response-time range | Not recorded | 1.03–8.43 s | 14.52–29.29 s |

Three revised answers required the one permitted repair. The memory question (Q4), which returned no passages in the baseline, now retrieves supporting learning/memory passages.

**These are delivery and validation outcomes, not independently graded accuracy scores.** These 15 questions were used during development and are not a held-out benchmark. The tester report did not include raw verifier decisions, so its ten rejections cannot all be classified as factual errors.

| Q | Question | Tester | Fresh baseline | Revised |
| --- | --- | --- | --- | --- |
| 1 | I built a product, but only friends praise it. What should I test next? | invalid_evidence | invalid_evidence | answered |
| 2 | Online sales have stopped growing. Should I approach stores? | invalid_evidence | invalid_evidence | answered |
| 3 | I spend hours copying emails and data. Can AI handle this? | answered | invalid_evidence | answered |
| 4 | I understand lessons today but forget them next week. Why? | insufficient_evidence | insufficient_evidence | answered |
| 5 | I unlock my phone without thinking while studying. How do I stop? | invalid_evidence | invalid_evidence | answered |
| 6 | I rest every Sunday but still feel exhausted on Monday. | answered | invalid_evidence | answered |
| 7 | I deliver my work, yet others get promoted. What am I missing? | invalid_evidence | answered | answered |
| 8 | My boss's plan seems wrong. How should I raise it? | answered | invalid_evidence | answered |
| 9 | Should I buy another course or build something practical? | invalid_evidence | invalid_evidence | answered |
| 10 | EMIs consume my salary despite regular raises. What should change? | invalid_evidence | invalid_evidence | answered |
| 11 | A caller claiming to be my bank creates urgency. How do I judge it? | invalid_evidence | invalid_evidence | answered |
| 12 | Diabetes runs in my family. What habits matter now? | invalid_evidence | invalid_evidence | answered |
| 13 | My partner apologises but repeats the same behaviour. What should I notice? | invalid_evidence | answered | answered |
| 14 | I work best late at night. Am I harming my performance? | answered | invalid_evidence | answered |
| 15 | Work thoughts continue after office hours. How do I switch off? | invalid_evidence | invalid_evidence | answered |

## Remaining issues found by manual review

- Q9 gives a general verdict in favor of practical building and adds a college-degree exception. This needs a closer comparison of both options and better relevance to the actual question.
- Q10 uses population debt/wage statistics in a personal finance answer and omits the source’s exclusion of home loans from its debt ratio. Such statistics should retain their scope or be omitted.
- Q13 applies a discussion of repeatedly choosing similar partners to a partner repeatedly apologizing for behavior. That changes the relationship being explained; the answer should acknowledge the gap rather than imply an explanation.
- Some answers still exceed the requested brevity. More text creates more opportunities for unsupported claims.
- During development, both mini and a trial of full GPT-4.1 approved suspect causal attributions and universal claims. A larger reviewer alone did not resolve this, so the default model was retained.

These are observed errors, not hypothetical caveats. The structured checks prevent skipped reviews and forged references, but do not guarantee correct interpretation. The next quality gate should use human-labelled support/contradiction examples, including wrong causes, wrong subjects, missing conditions and insufficient evidence, on questions not used to tune the prompts.

## Validation and operational evidence

- 116 Python tests and 9 frontend tests passed. Regression coverage includes stale/altered captions, scope restrictions, missing/false sentence checks, unsupported summaries, forged support spans, constrained citation choices and repair exhaustion.
- Desktop and mobile browser checks passed with 50 ready videos and imports disabled. A live source-scoped answer passed, its timestamp links were validated, and its saved response reopened correctly.
- Browser recording: `8f8ae77ea0774ddd8ed1b8bbe80bd6cf`; diagnostic `1789293911794996000` includes retrieval decisions and all checks.
- All five synthetic live verifier controls passed: faithful paraphrase, invented guarantees, invented history, personal causes and unsupported summaries. See `data/accuracy-review/verifier-controls.json`. Their success did not predict every real-caption failure above.
- Additional retrieval controls are recorded separately in `data/accuracy-review/final-controls.json`. The exact-future-stock-price question was correctly withheld, and the Hinglish memory question returned an answer. An unavailable personal-bank-balance question hit a provider error twice in the final run; the failure was surfaced, not converted into an answer. That question was withheld in an earlier run, but the final run cannot be counted as a successful abstention.

## Measured API usage

The final revised 15-question run used 339,990 OpenAI input tokens and 20,505 output tokens across planning, ranking, generation, verification and repairs. At the published GPT-4.1 mini uncached rates ($0.40/M input, $1.60/M output), this estimates **$0.169 for that run, or $0.0113 per question**. The fresh baseline estimates $0.0412 for 15 questions. These are token-based estimates, not billed totals; cache discounts may lower them, and Supermemory search charges are additional. Development reruns, reviewer experiments, controls and the browser query are excluded from these final-run figures. [Official model pricing](https://developers.openai.com/api/docs/models/gpt-4.1-mini).

## Reproduce and inspect

```sh
.venv/bin/python -m unittest discover -s tests
node tests/web_smoke.cjs
# Live commands consume API credits; existing result rows are reused.
.venv/bin/python tests/evaluate_direct_queries.py
.venv/bin/python tests/evaluate_verifier_controls.py
.venv/bin/python tests/evaluate_direct_queries.py --fixture tests/fixtures/retrieval_controls.json --output data/accuracy-review/new-controls.json --improved-only
```

Archive the existing output file before an entirely fresh evaluation. Canonical captions, raw audits, recordings and credentials remain local and ignored by Git. The updated reader is running at `http://127.0.0.1:8765`.
