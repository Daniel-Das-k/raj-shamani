"""Opt-in paired live evaluation; reads existing captions and never runs an import worker.
Run: .venv/bin/python tests/evaluate_direct_queries.py [--case-ids 1 2]
Baseline source snapshots live under data/accuracy-review and are kept out of Git.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import time
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from knowledge.channel_library import ChannelLibrary
from knowledge.caption_answers import answer_captions
from knowledge.evidence_answers import answer_from_evidence
from knowledge.video_guide import recommend_moments
from knowledge.providers import OpenAIJSON
from knowledge.raj_library import RajShamaniLibrary
from knowledge.server import load_settings, safe_error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-ids', type=int, nargs='+')
    parser.add_argument('--fixture', type=Path, default=Path('tests/fixtures/direct_query_review.json'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--improved-only', action='store_true')
    parser.add_argument('--answer-strategy', choices=['legacy', 'isolated_statements', 'isolated_summaries', 'video_guide'], default=RajShamaniLibrary.answer_strategy)
    parser.add_argument('--replay-results', type=Path, help='Reuse saved retrieval for unchanged questions; no Supermemory requests.')
    args = parser.parse_args()
    load_settings()
    root = Path('data/accuracy-review')
    root.mkdir(parents=True, exist_ok=True)
    def module(name):
        mod = types.ModuleType('knowledge.evaluation_' + name)
        mod.__package__ = 'knowledge'
        snapshot = root / (name + '-baseline.py')
        if not snapshot.exists():
            snapshot.write_bytes(subprocess.check_output(['git', 'show', f'fe4048a:knowledge/{name}.py']))
        exec(snapshot.read_text(), mod.__dict__)
        return mod
    baseline = module('caption_answers')
    baseline.verify_answer = module('answers').verify_answer
    class MeteredLLM(OpenAIJSON):
        def __init__(self):
            self.calls = []
        def complete(self, system, data, **kwargs):
            result = super().complete(system, data, **kwargs)
            kind = ('guide_review' if 'recommendation' in data else 'guide_selection' if 'summaries' in data else 'guide_description' if 'excerpt' in data
                    else 'verification' if 'items' in data else 'reference_summary' if 'reference_excerpt' in data else 'source_reading' if 'passage' in data
                    else 'statement_selection' if 'rejected_ids' in data else 'repair' if 'previous_draft' in data
                    else 'ranking' if 'Select evidence' in system or 'Select up to SIX' in system else 'planning' if 'search queries' in system or 'Plan a search' in system else 'generation')
            self.calls.append({'kind': kind, **self.last_usage})
            return result
    llm = MeteredLLM()
    library = RajShamaniLibrary(Path('data'), llm=llm)
    library.answer_strategy = args.answer_strategy
    cases = json.loads(args.fixture.read_text())['cases']
    replay = {c['id']: c for c in json.loads(args.replay_results.read_text())['cases']} if args.replay_results else {}
    path = args.output or root / f'{args.answer_strategy}-results.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    report = json.loads(path.read_text()) if path.exists() else {'model': llm.model_name, 'baseline_commit': 'fe4048a', 'cases': []}
    if path.exists() and report.get('run_metadata', {}).get('answer_strategy') != args.answer_strategy:
        raise SystemExit('Existing results use a different strategy. Choose a new output filename.')
    report.setdefault('run_metadata', {
        'started_at': datetime.now(timezone.utc).isoformat(), 'fixture': str(args.fixture),
        'answer_strategy': args.answer_strategy, 'replayed_retrieval_from': str(args.replay_results) if args.replay_results else None,
        'code_sha256': {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in [
            'knowledge/caption_retrieval.py', 'knowledge/caption_answers.py', 'knowledge/evidence_answers.py', 'knowledge/video_guide.py', 'knowledge/reference_summaries.py', 'knowledge/answer_language.py', 'knowledge/answers.py', 'knowledge/providers.py']},
        'ready_sources': [{'id': v['id'], 'revision': v['revision']} for v in library.ready_videos()],
    })
    def save():
        encoded = json.dumps(report, ensure_ascii=False, indent=2)
        for key in ['OPENAI_API_KEY', 'SUPERMEMORY_API_KEY', 'GROQ_API_KEY', 'DEEPGRAM_API_KEY', 'HF_TOKEN']:
            value = os.getenv(key)
            if value:
                encoded = encoded.replace(json.dumps(value, ensure_ascii=False)[1:-1], '[redacted]')
        path.write_text(encoded + '\n')
    for case in cases:
        if args.case_ids and case['id'] not in args.case_ids:
            continue
        row = next((r for r in report['cases'] if r['id'] == case['id']), None)
        if row is not None and (row['question'] != case['question'] or row.get('source_id') != case.get('source_id')):
            raise SystemExit('Existing results use a different question or scope. Choose a new output filename.')
        if row is None:
            row = {**case}
            report['cases'].append(row)
        for mode in (['improved'] if args.improved_only else ['baseline', 'improved']):
            if mode in row:
                continue
            start = time.monotonic()
            llm.calls = []
            audit = {}
            print(case['id'], mode, 'starting', flush=True)
            try:
                if mode == 'improved' and replay:
                    original = replay[case['id']]
                    if original['question'] != case['question'] or original.get('source_id') != case.get('source_id'):
                        raise ValueError('Replay requires the identical question and video scope.')
                    previous = original['improved']
                    retrieved = {'excerpts': previous['citations'], 'retrieval': previous['retrieval']}
                else:
                    retrieved = ChannelLibrary.search(library, case['question'], case.get('source_id')) if mode == 'baseline' else library.search(case['question'], case.get('source_id'))
                citations = retrieved['excerpts']
                sources = {}
                for cite in citations:
                    video = library.store.rows('SELECT revision FROM videos WHERE id=?', (cite['source_id'],))[0]
                    sources[cite['source_id']] = json.loads((library.directory / f"{cite['source_id']}-{video['revision'][:12]}.json").read_text())
                fn = baseline.answer_captions if mode == 'baseline' else {'video_guide': recommend_moments,
                     'isolated_statements': answer_from_evidence}.get(args.answer_strategy, answer_captions)
                kwargs = {'max_repairs': 1} if mode == 'improved' else {}
                if mode == 'improved' and args.answer_strategy == 'isolated_summaries':
                    kwargs['isolate_summaries'] = True
                if retrieved.get('clarifying_question'):
                    answer = {'status': 'needs_clarification', 'message': retrieved['clarifying_question'], 'points': []}
                    audit['final_status'] = 'needs_clarification'
                else:
                    answer = fn(case['question'], citations, sources, llm, audit, whole_passages=True, **kwargs)
                row[mode] = {'answer': answer, 'audit': audit, 'retrieval': retrieved.get('retrieval'),
                             'citations': citations, 'calls': llm.calls, 'seconds': round(time.monotonic() - start, 3)}
                print(case['id'], mode, answer['status'], len(citations), 'passages', row[mode]['seconds'], 'seconds', flush=True)
            except Exception as exc:
                row[mode] = {'error': safe_error(exc), 'http_status': getattr(exc, 'status_code', None),
                             'error_type': type(exc).__name__, 'calls': llm.calls,
                             'seconds': round(time.monotonic() - start, 3)}
                print(case['id'], mode, row[mode]['error_type'], row[mode]['http_status'], flush=True)
                save()
                raise SystemExit('Stopped on provider or runtime error; review before more calls.')
            save()
    print('Saved paired evaluation:', path, flush=True)


if __name__ == '__main__':
    main()
