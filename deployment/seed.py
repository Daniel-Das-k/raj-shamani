"""Initialize an empty persistent disk without copying developer answer history."""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3


def seed(source, destination):
    source, destination = Path(source), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    catalog = destination / 'channels.sqlite3'
    if not catalog.exists():
        temporary = catalog.with_suffix('.sqlite3.tmp')
        with sqlite3.connect(f'file:{source / "channels.sqlite3"}?mode=ro', uri=True) as original:
            with sqlite3.connect(temporary) as copied:
                original.backup(copied)
        temporary.replace(catalog)
    caption_dir = destination / 'supermemory-trial' / 'timed-captions'
    caption_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f'file:{catalog}?mode=ro', uri=True) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('The persistent catalog failed its integrity check.')
        rows = db.execute("SELECT v.id,v.revision FROM videos v JOIN channel_videos c ON c.video_id=v.id WHERE c.channel_id=? AND v.state='ready'",
                          ('UCzwCEE_PchiBULMnAJqhGVg',)).fetchall()
    if not rows:
        raise RuntimeError('The archive has no ready videos. Refusing to start an empty deployment.')
    for video_id, revision in rows:
        name = f'{video_id}-{revision[:12]}.json'
        target = caption_dir / name
        if not target.exists():
            temporary = target.with_suffix('.json.tmp')
            shutil.copyfile(source / 'supermemory-trial' / 'timed-captions' / name, temporary)
            temporary.replace(target)
        record = json.loads(target.read_text())
        if record.get('id') != video_id or record.get('revision') != revision or not record.get('segments'):
            raise RuntimeError('An original caption file failed its identity check.')
    print(f'Persistent archive verified: {len(rows)} videos. Existing user data preserved.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    seed(args.source, args.destination)
