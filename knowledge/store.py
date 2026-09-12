"""A small local collection with multilingual vector + keyword retrieval."""
from __future__ import annotations

import json
import math
from pathlib import Path
import sqlite3
import unicodedata


def keyword_tokens(text: str) -> list[str]:
    """Keep Indic combining marks with their letters; quote tokens before FTS use."""
    normalized = unicodedata.normalize("NFC", text)
    separated = "".join(char if unicodedata.category(char)[0] in "LNM" else " " for char in normalized)
    return list(dict.fromkeys(separated.split()))[:40]


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL,
                revision TEXT NOT NULL, metadata TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
                payload TEXT NOT NULL, vector TEXT NOT NULL, model TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS chunks_source ON chunks(source_id);
            CREATE VIRTUAL TABLE IF NOT EXISTS chunk_search USING fts5(id UNINDEXED, text);
            CREATE TABLE IF NOT EXISTS translations (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        """)

    def close(self):
        self.db.close()

    def translation(self, key: str):
        row = self.db.execute("SELECT payload FROM translations WHERE id = ?", (key,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def save_translation(self, key: str, value: dict):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO translations VALUES (?, ?)",
                            (key, json.dumps(value, ensure_ascii=False)))

    def sources(self) -> list[dict]:
        return [dict(row) for row in self.db.execute("""
            SELECT s.id, s.title, s.url, COUNT(c.id) AS chunks
            FROM sources s LEFT JOIN chunks c ON c.source_id = s.id GROUP BY s.id ORDER BY s.title
        """)]

    def indexed(self, source_id: str, revision: str, model: str) -> bool:
        row = self.db.execute("SELECT revision FROM sources WHERE id = ?", (source_id,)).fetchone()
        models = self.db.execute("SELECT DISTINCT model FROM chunks WHERE source_id = ?", (source_id,)).fetchall()
        return bool(row and row["revision"] == revision and models and all(r["model"] == model for r in models))

    def replace(self, source: dict, chunks: list[dict], vectors: list[list[float]], model: str):
        if not chunks or len(chunks) != len(vectors):
            raise ValueError("Every transcript chunk needs an embedding.")
        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) != 1 or not next(iter(dimensions)):
            raise ValueError("Embeddings have inconsistent dimensions.")
        for chunk, vector in zip(chunks, vectors):
            if chunk["source_id"] != source["id"] or any(not math.isfinite(v) for v in vector):
                raise ValueError("Invalid source or embedding.")
        with self.db:
            self.db.execute("DELETE FROM chunk_search WHERE id IN (SELECT id FROM chunks WHERE source_id = ?)", (source["id"],))
            self.db.execute("DELETE FROM chunks WHERE source_id = ?", (source["id"],))
            self.db.execute("""INSERT INTO sources VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET url=excluded.url, title=excluded.title,
                revision=excluded.revision, metadata=excluded.metadata""",
                            (source["id"], source["url"], source["title"], source["revision"], json.dumps(source)))
            for chunk, vector in zip(chunks, vectors):
                self.db.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?)",
                                (chunk["id"], source["id"], json.dumps(chunk, ensure_ascii=False), json.dumps(vector), model))
                self.db.execute("INSERT INTO chunk_search VALUES (?, ?)", (chunk["id"], chunk["text"]))

    def search(self, queries: list[str], embedder, limit: int = 8, *,
               source_ids: list[str] | None = None, diversify: bool = False) -> list[dict]:
        if not 1 <= limit <= 20:
            raise ValueError("Search limit must be between 1 and 20.")
        queries = list(dict.fromkeys(q.strip() for q in queries if q.strip()))[:4]
        if not queries:
            return []
        source_ids = list(dict.fromkeys(source_ids or []))
        source_filter = " AND c.source_id IN (" + ",".join("?" for _ in source_ids) + ")" if source_ids else ""
        rows = self.db.execute("""SELECT c.*, s.title, s.url FROM chunks c
            JOIN sources s ON s.id = c.source_id WHERE 1=1""" + source_filter, source_ids).fetchall()
        if not rows:
            return []
        if any(row["model"] != embedder.model_name for row in rows):
            raise ValueError("Embedding model changed; ingest the sources again to rebuild their embeddings.")
        passages = {row["id"]: {**json.loads(row["payload"]), "title": row["title"], "url": row["url"]} for row in rows}
        vectors = {row["id"]: json.loads(row["vector"]) for row in rows}
        scores = dict.fromkeys(passages, 0.0)
        query_vectors = embedder.encode(queries, query=True)
        for query, vector in zip(queries, query_vectors, strict=True):
            if any(len(v) != len(vector) for v in vectors.values()):
                raise ValueError("Stored and query embedding dimensions differ; rebuild the index.")
            ranked = sorted(vectors, key=lambda key: sum(a * b for a, b in zip(vector, vectors[key])), reverse=True)
            if not diversify:
                ranked = ranked[:30]
            # Reciprocal rank fusion avoids treating cosine similarity as confidence.
            for rank, key in enumerate(ranked, 1):
                scores[key] += 1 / (60 + rank)
            tokens = keyword_tokens(query)
            if tokens:
                expression = " OR ".join('"' + token + '"' for token in tokens)
                lexical = self.db.execute("""SELECT chunk_search.id FROM chunk_search
                    JOIN chunks c ON c.id = chunk_search.id WHERE chunk_search MATCH ?""" +
                    source_filter + " ORDER BY rank LIMIT 30", [expression, *source_ids]).fetchall()
                for rank, row in enumerate(lexical, 1):
                    scores[row["id"]] += 1 / (60 + rank)
        selected = []
        ranked_keys = sorted(scores, key=scores.get, reverse=True)
        if diversify:
            # Round-robin the best moments from each video for cross-video questions.
            by_source = {}
            for key in ranked_keys:
                by_source.setdefault(passages[key]["source_id"], []).append(key)
            ranked_keys = [group[index] for index in range(max(map(len, by_source.values())))
                           for group in by_source.values() if index < len(group)]
        for key in ranked_keys:
            if scores[key] == 0:
                continue
            passage = passages[key]
            # Suppress mostly duplicated windows, but allow several useful moments per episode.
            if any(other["source_id"] == passage["source_id"] and
                   max(0, min(other["end"], passage["end"]) - max(other["start"], passage["start"])) /
                   max(.001, min(other["end"] - other["start"], passage["end"] - passage["start"])) > .65
                   for other in selected):
                continue
            selected.append({**passage, "retrieval_score": scores[key]})
            if len(selected) == limit:
                break
        return selected
