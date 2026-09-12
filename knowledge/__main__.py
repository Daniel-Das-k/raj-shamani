from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .answers import ask, render_answer
from .ingest import ingest, links_from_file
from .providers import Embedder, GroqJSON
from .store import Store
from .transcripts import citation

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="Build a video knowledge base and ask questions with timestamped evidence.")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="Local collection directory")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("ingest", help="Download, transcribe, and index whole YouTube videos")
    add.add_argument("urls", nargs="*")
    add.add_argument("--links-file", type=Path, help="Read YouTube links from a Markdown/text file")
    commands.add_parser("sources", help="List indexed videos")
    search = commands.add_parser("search", help="Find transcript passages without generating an answer")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5, choices=range(1, 21))
    answer = commands.add_parser("ask", help="Answer questions from the videos in your collection")
    answer.add_argument("question")
    answer.add_argument("--json", action="store_true", help="Return structured answer data")
    answer.add_argument("--translate", action="store_true", help="Include cached English translations of cited excerpts")
    serve = commands.add_parser("serve", help="Run the local browser demo")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--links-file", type=Path, default=ROOT / "LINKS.md")
    serve.add_argument("--backend", choices=["supermemory", "local"], default="supermemory")
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    data_dir = args.data_dir.expanduser().resolve()
    os.environ.setdefault("HF_HOME", str(ROOT / "cache" / "huggingface"))
    if args.command == "serve":
        from .server import serve
        serve(data_dir, args.links_file, args.port, args.backend)
        return 0
    store = Store(data_dir / "knowledge.sqlite3")
    embedder = Embedder(ROOT / "cache" / "embeddings")
    try:
        if args.command == "ingest":
            urls = [*args.urls, *(links_from_file(args.links_file) if args.links_file else [])]
            if not urls:
                raise ValueError("Supply YouTube URLs or --links-file LINKS.md.")
            failures = 0
            for url in dict.fromkeys(urls):
                try:
                    print(json.dumps(ingest(url, data_dir, store, embedder), ensure_ascii=False, indent=2))
                except Exception as exc:
                    failures += 1
                    print(f"Could not ingest {url}: {exc}", file=sys.stderr)
            return 1 if failures else 0
        if args.command == "sources":
            print(json.dumps(store.sources(), ensure_ascii=False, indent=2))
        elif args.command == "search":
            passages = store.search([args.query], embedder, args.limit)
            results = [citation(p, p["words"][0]["index"], p["words"][-1]["index"]) for p in passages]
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            result = ask(args.question, store, embedder, GroqJSON(), translate=args.translate)
            print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render_answer(result))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
