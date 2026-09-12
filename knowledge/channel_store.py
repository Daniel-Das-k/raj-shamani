"""Persistent channel catalog and resumable, single-worker ingestion queue."""
from __future__ import annotations

from contextlib import contextmanager
import sqlite3
import time


class ChannelStore:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS channels (
                  id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL, handle TEXT,
                  state TEXT NOT NULL DEFAULT 'queued', paused INTEGER NOT NULL DEFAULT 0,
                  error TEXT, synced_at REAL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS videos (
                  id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL,
                  state TEXT NOT NULL DEFAULT 'queued', error TEXT, document_id TEXT,
                  revision TEXT, segments INTEGER NOT NULL DEFAULT 0,
                  attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                  updated_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS channel_videos (
                  channel_id TEXT NOT NULL REFERENCES channels(id), video_id TEXT NOT NULL REFERENCES videos(id),
                  PRIMARY KEY(channel_id, video_id));
                CREATE INDEX IF NOT EXISTS video_queue ON videos(state, next_attempt);
                CREATE INDEX IF NOT EXISTS video_channels ON channel_videos(video_id);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def execute(self, sql, args=()):
        with self.connect() as db:
            db.execute(sql, args)

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, args)]

    def add_channel(self, channel):
        with self.connect() as db:
            db.execute("INSERT INTO channels(id,title,url,handle,created_at) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,handle=excluded.handle",
                       (channel["id"], channel["title"], channel["url"], channel.get("handle"), time.time()))

    def add_video(self, video, channel_id=None):
        with self.connect() as db:
            db.execute("INSERT INTO videos(id,title,url,state,error,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title",
                       (video["id"], video["title"], video["url"], "skipped" if video.get("unavailable") else "queued",
                        "Private, restricted, live or upcoming video." if video.get("unavailable") else None, time.time()))
            if channel_id:
                db.execute("INSERT OR IGNORE INTO channel_videos VALUES(?,?)", (channel_id, video["id"]))

    def channel_action(self, channel_id, action):
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM channels WHERE id=?", (channel_id,)).fetchone():
                raise ValueError("Unknown channel.")
            if action == "pause":
                db.execute("UPDATE channels SET paused=1 WHERE id=?", (channel_id,))
            elif action == "resume":
                db.execute("UPDATE channels SET paused=0 WHERE id=?", (channel_id,))
            elif action == "sync":
                db.execute("UPDATE channels SET state='queued',paused=0,error=NULL WHERE id=? AND state!='scanning'", (channel_id,))
            elif action == "retry":
                db.execute("UPDATE videos SET state=CASE WHEN document_id IS NULL THEN 'queued' ELSE 'indexing' END,error=NULL,attempts=0,next_attempt=0 WHERE state IN ('error','skipped') AND id IN (SELECT video_id FROM channel_videos WHERE channel_id=?)", (channel_id,))
                db.execute("UPDATE channels SET paused=0,state=CASE WHEN state='error' THEN 'queued' ELSE state END,error=NULL WHERE id=?", (channel_id,))
            else:
                raise ValueError("Unknown channel action.")

    def recover(self):
        # Caller must hold the exclusive worker lock before recovering abandoned work.
        self.execute("UPDATE channels SET state='queued' WHERE state='scanning'")
        self.execute("UPDATE videos SET state=CASE WHEN document_id IS NULL THEN 'queued' ELSE 'indexing' END WHERE state='processing'")

    def update_video(self, video_id, **fields):
        allowed = {"state", "error", "document_id", "revision", "segments", "attempts", "next_attempt"}
        if not fields or not fields.keys() <= allowed:
            raise ValueError("Invalid video update.")
        fields["updated_at"] = time.time()
        self.execute("UPDATE videos SET " + ",".join(k + "=?" for k in fields) + " WHERE id=?", (*fields.values(), video_id))

    def eligible(self):
        return """(NOT EXISTS(SELECT 1 FROM channel_videos cv WHERE cv.video_id=v.id)
                OR EXISTS(SELECT 1 FROM channel_videos cv JOIN channels c ON c.id=cv.channel_id
                          WHERE cv.video_id=v.id AND c.paused=0))"""

    def next_video(self, *, serial=False, video_ids=None):
        if video_ids == []:
            return None
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            states = "('queued','indexing')"
            if serial and db.execute("SELECT 1 FROM videos v WHERE state IN ('indexing','processing') AND " + self.eligible() + " LIMIT 1").fetchone():
                states = "('indexing')"
            selection, ordering, args = '', '', [time.time()]
            if video_ids is not None:
                selection = ' AND v.id IN (' + ','.join('?' for _ in video_ids) + ')'
                args.extend(video_ids)
                ordering = 'CASE v.id ' + ' '.join(f'WHEN ? THEN {i}' for i in range(len(video_ids))) + ' END,'
                args.extend(video_ids)
            row = db.execute("SELECT v.* FROM videos v WHERE state IN " + states + " AND next_attempt<=? AND " + self.eligible() + selection + " ORDER BY CASE state WHEN 'indexing' THEN 0 ELSE 1 END," + ordering + "updated_at LIMIT 1", args).fetchone()
            if row:
                db.execute("UPDATE videos SET state='processing' WHERE id=?", (row["id"],))
            return dict(row) if row else None

    def page(self, offset=0, limit=50, status=""):
        filters = {"": "1=1", "ready": "state='ready'",
                   "pending": "state IN ('queued','processing','indexing')",
                   "attention": "state IN ('error','skipped')"}
        if status not in filters:
            raise ValueError("Invalid video status filter.")
        return self.rows("SELECT *,state AS status,segments AS chunks FROM videos WHERE " + filters[status] + " ORDER BY CASE state WHEN 'ready' THEN 0 WHEN 'processing' THEN 1 WHEN 'error' THEN 2 ELSE 3 END,updated_at DESC,id LIMIT ? OFFSET ?", (limit, offset))

    def status(self):
        counts = {r["state"]: r["n"] for r in self.rows("SELECT state,count(*) n FROM videos GROUP BY state")}
        channels = self.rows("SELECT * FROM channels ORDER BY created_at DESC")
        for channel in channels:
            channel["counts"] = {r["state"]: r["n"] for r in self.rows("SELECT v.state,count(*) n FROM videos v JOIN channel_videos cv ON cv.video_id=v.id WHERE cv.channel_id=? GROUP BY v.state", (channel["id"],))}
        return {"channels": channels, "counts": counts, "total": sum(counts.values()), "sources": self.page()}
