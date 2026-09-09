"""Readable transcript for review while speaker model access is pending."""
import json
from pathlib import Path

root = Path(__file__).resolve().parent
raw = json.loads((root / 'outputs/groq_raw.json').read_text(encoding='utf-8'))
lines = [
    '# Clip transcription — speaker labels pending', '',
    'Source: https://youtube.com/shorts/mX9pVUXsFJk', '',
    'Machine transcript. Wording and timing are unverified. Speaker separation has not run.',
    'Some English speech is rendered in Devanagari. Preserve this raw result when making corrections.',
    'Times refer to this 45.44-second clip, not the original podcast.', '',
]
for segment in raw['segments']:
    start, end = segment['start'], segment['end']
    lines.extend([f"**{start:.2f}–{end:.2f} seconds · speaker unassigned**", '', segment['text'].strip(), ''])
(root / 'outputs/transcript_for_review.md').write_text('\n'.join(lines), encoding='utf-8')
print('Saved readable raw transcript with segment timestamps.')
