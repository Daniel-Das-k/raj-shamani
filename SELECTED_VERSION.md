# Selected reader version: video guide

The current default is `RajShamaniLibrary.answer_strategy = 'video_guide'`, following
the user's request to connect people to useful channel content rather than force a
final answer. Cards show what a moment discusses, why it may help, its limitations,
and an original timestamp link. Direct and related discussions are distinguished;
no useful match is an acceptable result. The former direct-answer code remains
available as `isolated_statements`, and its committed checkpoint is `f3e6412`.

See [the video-guide evaluation](VIDEO_GUIDE_REVIEW.md) for the new results.

## Previous selection and preserved checkpoint

The previous reader default was `RajShamaniLibrary.answer_strategy = 'isolated_statements'`.
This is the source-by-source version selected earlier on 13 September 2026. It remains
available for comparisons. The guide change does not change the configured model.

Each passage is read separately, without the user's question. The app selects up to
three statements, checks each against its own original passage, and combines the
checked statements into one reply. Reference summaries reuse those statements, with
original captions and timestamp links available separately.

In the saved 15-question comparison, 11 replies were displayed. Assistant review
against the captions found 4 substantially supported replies, 6 needing revision,
and 1 material error. The earlier run had 3 supported replies, 4 needing revision,
and 4 material errors among its 11 displayed replies. This supports keeping this
version for source fidelity; it does not establish perfect answers or production
accuracy. Incomplete answers, repetition, and missing qualifications remain known issues.

See [the exact questions, replies and findings](RESPONSE_IMPROVEMENTS.md).
The selected raw run is `data/accuracy-review/wide-15-after-statements.json`;
validation is recorded in `data/accuracy-review/selected-workflow-validation.json`.
The `legacy` and `isolated_summaries` evaluation options remain available as experiments.

A local source checkpoint and SHA-256 manifest are saved under
`data/accuracy-review/checkpoints/`. The checkpoint excludes credentials, Git metadata
and indexed data. Original captions and response history remain in the existing
`data/` directory and must be retained separately.
