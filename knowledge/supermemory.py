"""Small SuperRAG client and isolated YouTube trial; no local model downloads.

Run `python -m knowledge.supermemory --help`. Direct URL results are experimental:
they are not imported into the word-timed citation index.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote

from .ingest import links_from_file, read_json, write_json
from .providers import require_key
from .transcripts import youtube_source

ROOT = Path(__file__).resolve().parent.parent
TRIAL = ROOT / "data" / "supermemory-trial"
CONTAINER = "knowledge-retriever-trial"


class Supermemory:
    def __init__(self, container=CONTAINER, session=None):
        if session is None:
            import requests
            session = requests.Session()
        self.session = session
        self.container = container

    def request(self, method, path, payload=None):
        import requests
        key = require_key("SUPERMEMORY_API_KEY")
        try:
            response = self.session.request(
                method, "https://api.supermemory.ai" + path,
                headers={"Authorization": "Bearer " + key}, json=payload,
                timeout=(15, 90), allow_redirects=False,
            )
        except requests.RequestException as exc:
            # Do not echo request headers or provider credentials into logs.
            raise RuntimeError(f"Supermemory connection failed ({type(exc).__name__}).") from None
        if not 200 <= response.status_code < 300:
            message = response.text[:1000].replace(key, "[redacted]")
            raise RuntimeError(f"Supermemory HTTP {response.status_code}: {message}")
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Supermemory returned an unexpected response.")
        return result

    def add(self, content, custom_id, metadata):
        return self.request("POST", "/v3/documents", {
            "content": content, "customId": custom_id, "containerTag": self.container,
            "taskType": "superrag", "metadata": metadata,
        })

    def document(self, document_id):
        return self.request("GET", "/v3/documents/" + quote(document_id, safe=""))

    def search_v3(self, query, *, limit=5, rerank=True):
        return self.request("POST", "/v3/search", {
            "q": query, "containerTag": self.container, "limit": limit,
            "rerank": rerank, "onlyMatchingChunks": True,
        })

    def search(self, query, *, limit=5, filters=None):
        payload = {
            "q": query, "containerTag": self.container, "limit": limit,
            "searchMode": "documents", "rerank": True, "aggregate": False,
        }
        if filters:
            payload["filters"] = filters
        return self.request("POST", "/v4/search", payload)


def start_trial(client, directory, urls):
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {"container": client.container, "videos": []}
    if manifest["container"] != client.container:
        raise ValueError("Trial manifest belongs to a different container.")
    known = {row["id"] for row in manifest["videos"]}
    for url in urls:
        source = youtube_source(url)
        if source["id"] in known:
            continue
        result = client.add(source["url"], "kr-url-trial-" + source["id"], {
            "video_id": source["id"], "video_url": source["url"],
            "trial": True, "timestamp_verified": False,
        })
        document_id = result.get("id")
        if not isinstance(document_id, str) or not document_id:
            raise ValueError("Supermemory did not return a document ID.")
        manifest["videos"].append({**source, "document_id": document_id, "status": result.get("status")})
        write_json(manifest_path, manifest)
        known.add(source["id"])
    return manifest


def trial_status(client, directory):
    manifest = read_json(directory / "manifest.json")
    results = []
    for source in manifest["videos"]:
        document = client.document(source["document_id"])
        write_json(directory / (source["id"] + ".json"), document)
        content = document.get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        results.append({**source, "status": document.get("status"), "type": document.get("type"),
                        "title": document.get("title"), "content_characters": len(content),
                        "timestamp_strings_present": bool(re.search(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", content)),
                        "preview": content[:800]})
    write_json(directory / "status.json", results)
    return results


def control_trial(client, directory):
    """A labeled text control isolates API indexing from YouTube extraction."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "control.json"
    if path.exists():
        saved = read_json(path)
    else:
        added = client.add(
            "Synthetic connection test, not video content. The test project codeword is cedar-seven.",
            "kr-synthetic-control-v1", {"synthetic": True, "trial": True},
        )
        saved = {"document_id": added["id"], "container": client.container}
        write_json(path, saved)
    document = client.document(saved["document_id"])
    result = {**saved, "status": document.get("status"), "synthetic": True}
    if document.get("status") == "done":
        write_json(directory / "control-document.json", document)
        result["search_v3"] = client.search_v3("What is the test project codeword?")
        result["search"] = client.search("What is the test project codeword?")
    write_json(directory / "control-result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description="Test SuperRAG on an isolated copy of the video links.")
    parser.add_argument("--data-dir", type=Path, default=TRIAL)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="Check access without uploading documents")
    commands.add_parser("control", help="Upload/check a synthetic text control in a separate container")
    add = commands.add_parser("add", help="Submit videos for direct URL extraction")
    add.add_argument("urls", nargs="*")
    add.add_argument("--links-file", type=Path)
    commands.add_parser("status", help="Fetch extraction results and save them locally")
    search = commands.add_parser("search", help="Retrieve experimental excerpts; does not generate an answer")
    search.add_argument("query")
    search.add_argument("--v3", action="store_true", help="Compare with the older v3 document-search endpoint")
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    client = Supermemory()
    try:
        if args.command == "check":
            result = client.search("video knowledge base connection test", limit=2)
            result = {"connected": True, "results": len(result.get("results", []))}
        elif args.command == "control":
            result = control_trial(Supermemory(CONTAINER + "-control"), args.data_dir)
        elif args.command == "add":
            urls = [*args.urls, *(links_from_file(args.links_file) if args.links_file else [])]
            if not urls:
                raise ValueError("Supply video URLs or --links-file LINKS.md.")
            result = start_trial(client, args.data_dir, urls)
        elif args.command == "status":
            result = trial_status(client, args.data_dir)
        else:
            result = client.search_v3(args.query) if args.v3 else client.search(args.query)
            args.data_dir.mkdir(parents=True, exist_ok=True)
            write_json(args.data_dir / "last-search.json", {"query": args.query, "response": result})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        message = str(exc)
        key = os.getenv("SUPERMEMORY_API_KEY")
        print(message.replace(key, "[redacted]") if key else message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
