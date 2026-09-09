"""Generate a local listening report from saved outputs, without API calls."""
import html
import json
import argparse
from pathlib import Path

root = Path(__file__).resolve().parent
out = root / 'outputs'
parser = argparse.ArgumentParser()
parser.add_argument('--speakers', type=int, choices=[1, 2, 3])
args = parser.parse_args()
export_dir = out if args.speakers is None else out / f'forced_{args.speakers}'
data = json.loads((export_dir / 'speaker_transcript.json').read_text(encoding='utf-8'))
raw = json.loads((out / ('speakers_raw.json' if args.speakers is None else f'speakers_forced_{args.speakers}.json')).read_text(encoding='utf-8'))
transcription = json.loads((out / 'transcription_run.json').read_text(encoding='utf-8'))
rows = []
for turn in data['turns']:
    start, end = turn['start'], turn['end']
    reasons = '; '.join(turn['review_reasons']) or 'No automatic timing flags'
    rows.append(f'''<article><button onclick="playRange({start},{end})">Play {start:.2f}–{end:.2f}s</button>
    <strong>{html.escape(turn['name'])}</strong><p lang="hi">{html.escape(turn['text'])}</p>
    <small>{html.escape(reasons)}</small></article>''')
labels = sorted({turn['speaker'] for turn in raw['regular']})
timeline = ''.join(f"<tr><td>{html.escape(turn['speaker'])}</td><td>{turn['start']:.3f}</td><td>{turn['end']:.3f}</td></tr>" for turn in raw['regular'])
report = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Raj Shamani clip — speaker review</title><style>
body{{font:17px/1.6 system-ui,sans-serif;max-width:850px;margin:36px auto;padding:0 20px;background:#faf9f6;color:#222}}
article{{background:white;padding:20px;margin:16px 0;border:1px solid #ddd;border-radius:10px}}
button{{padding:8px 12px;margin-right:12px;cursor:pointer}}small{{color:#745510}}audio{{width:100%}}
td,th{{padding:6px 18px;text-align:left}}p{{white-space:pre-wrap}}.note{{background:#fff0cb;padding:16px}}
</style><h1>Speaker transcript review</h1>
<p><a href="https://youtube.com/shorts/mX9pVUXsFJk">Original 45-second clip</a></p>
<p class="note">Machine output, not a verified transcript. Anonymous labels represent detected voices, not known identities.
Mixed Hindi-English wording and speaker changes require listening checks. Timestamps refer to this clip only.</p>
<p>Speaker count setting: {html.escape(raw['speaker_count_setting'])}. A forced count is an assumption, not independent evidence of the number of voices.</p>
<p>Detected voices: {len(labels)}. Groq request: {transcription['elapsed_seconds']:.2f} seconds.
Speaker-model run, including loading and any download: {raw['elapsed_seconds']:.2f} seconds.</p>
<audio id="player" controls src="{'../' if args.speakers is None else '../../'}audio.wav"></audio>
{''.join(rows)}<h2>Original audio-based speaker boundaries</h2>
<p>These boundaries come from the speaker model. Transcript boundaries above come from Groq word timestamps and can differ.</p>
<table><tr><th>Speaker</th><th>Start (s)</th><th>End (s)</th></tr>{timeline}</table>
<script>const player=document.getElementById('player');let stopAt=Infinity;
function playRange(start,end){{stopAt=end;player.currentTime=start;player.play();}}
player.addEventListener('timeupdate',()=>{{if(player.currentTime>=stopAt){{player.pause();stopAt=Infinity;}}}});
</script></html>'''
(export_dir / 'speaker_review.html').write_text(report, encoding='utf-8')
print(f'Saved listening report for {len(labels)} detected voices.')
