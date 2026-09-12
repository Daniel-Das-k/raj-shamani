"""Opt-in live diagnosis of one caption reply; never imports or resumes videos."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from knowledge.caption_answers import answer_captions
from knowledge.channel_library import ChannelLibrary
from knowledge.providers import GroqJSON
from knowledge.server import load_settings


if __name__ == "__main__":
    load_settings()
    question = 'can u tell me how the shopping in future will be like'
    library = ChannelLibrary(Path('data'))
    citations = library.search(question)['excerpts']
    sources = {}
    for cite in citations:
        video_id = cite['source_id']
        revision = library.store.rows('SELECT revision FROM videos WHERE id=?', (video_id,))[0]['revision']
        sources[video_id] = json.loads((library.directory / f'{video_id}-{revision[:12]}.json').read_text())
    audit = {'question': question, 'calls': []}
    class DiagnosticLLM(GroqJSON):
        def complete(self, system, data):
            result = super().complete(system, data)
            audit['calls'].append({'kind': 'verification' if 'items' in data else 'generation', 'result': result})
            return result
    result = answer_captions(question, citations, sources, DiagnosticLLM(), audit, whole_passages=True)
    audit['final'] = result
    directory = Path('data/ui-checks')
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'reply-diagnostic.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    print(json.dumps(audit, ensure_ascii=False, indent=2))
