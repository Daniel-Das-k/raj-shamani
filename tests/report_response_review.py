"""Render preserved before/after replies and check citation provenance offline."""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from knowledge.caption_retrieval import source_citation


def inspect(run):
    revisions = {v['id']: v['revision'] for v in run['run_metadata']['ready_sources']}
    issues, scope, durations, calls = [], [], [], []
    occurrences, ranges = 0, set()
    for case in run['cases']:
        result = case['improved']
        durations.append(result['seconds'])
        calls.extend(result['calls'])
        if case.get('source_id'):
            scope.append({'id': case['id'], 'retrieved_count': len(result.get('citations', [])),
                         'status': result.get('answer', {}).get('status'), 'all_in_scope': all(c['source_id'] == case['source_id']
                         for c in result.get('citations', []))})
        for point in result.get('answer', {}).get('points', []):
            for cite in point['citations']:
                occurrences += 1
                ranges.add((cite['source_id'], tuple(cite['segment_ids'])))
                try:
                    vid = cite['source_id']
                    source = json.loads(Path(f'data/supermemory-trial/timed-captions/{vid}-{revisions[vid][:12]}.json').read_text())
                    index = {s['id']: i for i, s in enumerate(source['segments'])}
                    original = source_citation(source, index[cite['segment_ids'][0]], index[cite['segment_ids'][-1]])
                    mismatches = [key for key, value in original.items() if cite.get(key) != value]
                    if mismatches:
                        issues.append({'id': case['id'], 'source_id': vid, 'fields': mismatches})
                except (OSError, KeyError, ValueError, IndexError) as exc:
                    issues.append({'id': case['id'], 'error': str(exc)})
    return {'statuses': dict(Counter(c['improved'].get('answer', {}).get('status', 'error') for c in run['cases'])),
            'total_citation_occurrences': occurrences, 'unique_citation_ranges': len(ranges),
            'provenance_issues': issues, 'scope_checks': scope,
            'median_seconds': statistics.median(durations), 'min_seconds': min(durations), 'max_seconds': max(durations),
            'llm_calls': len(calls), 'calls_by_kind': dict(Counter(c['kind'] for c in calls)),
            'input_tokens': sum(c.get('input_tokens', 0) for c in calls),
            'output_tokens': sum(c.get('output_tokens', 0) for c in calls)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, default=Path('data/accuracy-review/wide-15-results.json'))
    parser.add_argument('--after', type=Path, default=Path('data/accuracy-review/wide-15-after-statements.json'))
    parser.add_argument('--review', type=Path, default=Path('data/accuracy-review/wide-15-after-review.json'))
    parser.add_argument('--output', type=Path, default=Path('RESPONSE_IMPROVEMENTS.md'))
    args = parser.parse_args()
    before, after, review = [json.loads(p.read_text()) for p in (args.before, args.after, args.review)]
    previous = {c['id']: c for c in before['cases']}
    assessments = {c['id']: c for c in review['cases']}
    old_stats, stats = inspect(before), inspect(after)
    args.after.with_name(args.after.stem + '-integrity.json').write_text(json.dumps(stats, indent=2) + '\n')
    lines = ['# Response improvements and saved replies', '',
        '13 September 2026 · 50 indexed Raj Shamani videos · GPT-4.1 mini · same 15 questions before and after.', '',
        review['summary'], '',
        'These are assistant assessments against the saved captions, not independent human grades or production accuracy estimates. '
        'These questions were used during development. Retrieval was run afresh, so this comparison measures the whole pipeline; '
        'it does not isolate the effect of answer generation. Separate replay pilots preserve experiments using unchanged retrieval.', '',
        '## Changes', '',
        '- Read each passage independently without the user question. Extract up to three short statements per passage; validate source unit IDs and language.',
        '- Select at most three statement IDs. The selector cannot add prose. Python joins the selected statements into one paragraph.',
        '- Verify each selected statement against only its own original passage. Exclude a failed statement and allow one reselection; already checked unchanged statements can be reused.',
        '- Reuse checked statements for the summaries of their own references. Construct canonical timestamp links from original captions and keep the original excerpt expandable.',
        '- Enforce Hindi/Tamil script and basic Hinglish language checks. Clarify missing user context before retrieval. Preserve uncertainty, opinions and event phases in the instructions; these checks still have measured limits.',
        '- Keep the existing local response history and diagnostic records, including refusals and errors.', '',
        '## Measured outcomes', '', '| Measure | Before | After |', '| --- | ---: | ---: |']
    for name in ('answered', 'invalid_evidence', 'insufficient_evidence', 'needs_clarification', 'error'):
        lines.append(f"| {name} | {old_stats['statuses'].get(name, 0)} | {stats['statuses'].get(name, 0)} |")
    lines.extend([f"| Median total response time | {old_stats['median_seconds']:.2f} s | {stats['median_seconds']:.2f} s |",
        f"| LLM calls | {old_stats['llm_calls']} | {stats['llm_calls']} |",
        f"| Input / output tokens | {old_stats['input_tokens']:,} / {old_stats['output_tokens']:,} | {stats['input_tokens']:,} / {stats['output_tokens']:,} |", '',
        f"Checked {stats['total_citation_occurrences']} displayed citation occurrences ({stats['unique_citation_ranges']} distinct ranges); "
        f"found {len(stats['provenance_issues'])} mismatches in original caption text, segment IDs, titles, timestamps or URLs. "
        'This is a provenance check, not proof of correct interpretation or audio alignment.', '',
        '## Review and remaining work', '', '| Question | Review | Finding |', '| --- | --- | --- |'])
    for c in after['cases']:
        r = assessments[c['id']]
        lines.append(f"| {c['id']} | {r['verdict']} | {r['finding'].replace('|', '/')} |")
    validation_path = Path('data/accuracy-review/selected-workflow-validation.json')
    if validation_path.exists():
        validation = json.loads(validation_path.read_text())
        lines.extend(['', '## App verification', '',
            f"{validation['python_tests']} Python tests and {validation['frontend_tests']} frontend tests passed. "
            'A live Chrome check passed on desktop and mobile with no page errors. The answer appeared as one paragraph, '
            'reference summaries were displayed above expandable original captions, and the exact saved reply reopened after reload.', '',
            f"Browser record: `{validation['record_id']}`. Saved browser evidence: `data/ui-checks/evidence-response/`. "
            'The local server runs the selected statement workflow. The collection still contains 50 indexed videos and imports remain disabled.', '',
            'After the selected run, canonical citation metadata validation was added and the unchanged language helpers were moved into a shared module. '
            'The selected workflow uses the same reading, selection and verification prompts as that run. '
            'The reference integrity check above and offline regressions cover the added validation.'])
    lines.extend(['', '## Saved data and reproduction', '',
        f'- Original run: `{args.before}`.', f'- New run: `{args.after}`.', f'- Evidence review: `{args.review}`.',
        '- Development experiments (not the selected app workflow): `isolated-pilot.json`, `blind-reading-pilot.json`, `wide-15-final-responses.json`, `wide-15-compact-responses.json` and `full-model-diagnostic.json`, all under `data/accuracy-review/`. These include weaker outputs and have been preserved unchanged.',
        '- Normal app queries and exact replies: `data/responses.sqlite3`; evidence decisions: `data/response-diagnostics/`.',
        '- Raw files contain the retrieved captions, generated readings, rejected selections, check results, timing and token usage. They stay local under ignored `data/`; this readable report contains all 15 exact before/after replies and their displayed references.', '',
        'Offline report regeneration: `.venv/bin/python tests/report_response_review.py`.', '',
        'Live rerun (incurs configured API usage; use a new output filename):', '', '```sh',
        '.venv/bin/python tests/evaluate_direct_queries.py --fixture tests/fixtures/wide_query_review.json --improved-only --answer-strategy isolated_statements --output data/accuracy-review/new-run.json',
        '```', '', '## Exact questions, replies and references', '',
        'The text below is preserved as generated, including remaining weaknesses; it has not been rewritten to improve the score.', ''])
    for case in after['cases']:
        old = previous[case['id']]
        if old['question'] != case['question'] or old.get('source_id') != case.get('source_id'):
            raise ValueError('Cannot compare different questions or video scopes.')
        lines.extend([f"### {case['id']}. {case['category']}", '', case['question'], ''])
        if case.get('source_id'):
            lines.extend([f"Selected video: `{case['source_id']}`.", ''])
        for label, row in [('Before', old), ('After', case)]:
            result = row['improved']
            answer = result.get('answer', {})
            lines.extend([f"**{label}** — `{answer.get('status', 'error')}` · {result['seconds']:.2f} seconds", ''])
            texts = [p['text'] for p in answer.get('points', [])] or [answer.get('message') or result.get('error', 'No response')]
            for text in texts:
                lines.extend(['\n'.join('> ' + line for line in text.splitlines()), ''])
            for point in answer.get('points', []):
                for c in point['citations']:
                    lines.append(f"- [{c['time_range']} — {c['title']}]({c['url']}) — {c.get('summary', c['quote'])}")
            lines.append('')
        lines.extend([f"**Review:** {assessments[case['id']]['finding']}", ''])
    args.output.write_text('\n'.join(lines).rstrip() + '\n')
    print(json.dumps(stats, indent=2))
    print('Saved', args.output)


if __name__ == '__main__':
    main()
