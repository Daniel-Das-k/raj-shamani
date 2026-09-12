"""Loopback-only demo server with background ingestion and a small JSON API."""
from __future__ import annotations

from contextlib import closing
import copy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from uuid import uuid4
from urllib.parse import parse_qs, urlparse

from .answers import ask
from .ingest import ingest, links_from_file, read_json
from .providers import Embedder, OpenAIJSON
from .store import Store
from .transcripts import citation, youtube_source
from .translations import translate_citations
from .response_history import ResponseHistory

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "web"


def load_settings():
    from dotenv import dotenv_values
    # Read changes made to .env while the demo is running; never return key values.
    values = dotenv_values(ROOT / ".env")
    for key in ("DEEPGRAM_API_KEY", "SUPERMEMORY_API_KEY", "OPENAI_API_KEY", "OPENAI_CHAT_MODEL", "GROQ_API_KEY", "GROQ_CHAT_MODEL", "DEEPGRAM_DIARIZER"):
        if values.get(key):
            os.environ[key] = values[key]


class Demo:
    def __init__(self, data_dir: Path, links_file: Path, embedder=None, llm=None):
        self.data_dir = data_dir
        self.links_file = links_file
        self.database = data_dir / "knowledge.sqlite3"
        self.embedder = embedder or Embedder(ROOT / "cache" / "embeddings")
        self.llm = llm or OpenAIJSON()
        self.runtime_lock = threading.Lock()
        self.job_lock = threading.Lock()
        self.job = {"running": False, "items": []}
        with closing(Store(self.database)):
            pass

    def status(self):
        load_settings()
        with closing(Store(self.database)) as store:
            ready = {source["id"]: {**source, "status": "ready"} for source in store.sources()}
        error = None
        try:
            links = links_from_file(self.links_file)
        except (OSError, ValueError) as exc:
            links, error = [], str(exc)
        sources = []
        for url in links:
            source = youtube_source(url)
            metadata = self.data_dir / "sources" / source["id"] / "source.json"
            if metadata.exists():
                saved = read_json(metadata)
                source.update({key: saved.get(key) for key in ("title", "duration_seconds", "channel")})
            sources.append(ready.pop(source["id"], {**source, "status": "pending", "chunks": 0}))
        sources.extend(ready.values())
        with self.job_lock:
            job = copy.deepcopy(self.job)
        return {"sources": sources, "links_count": len(links), "links_error": error,
                "credentials": {"transcription": bool(os.getenv("DEEPGRAM_API_KEY")),
                                "answers": bool(os.getenv("OPENAI_API_KEY"))}, "job": job}

    def start_ingestion(self, urls=None):
        load_settings()
        if not os.getenv("DEEPGRAM_API_KEY"):
            raise ValueError("Add DEEPGRAM_API_KEY to the project .env file before processing podcasts.")
        if urls is None:
            urls = links_from_file(self.links_file)
        if not isinstance(urls, list) or not 1 <= len(urls) <= 20 or any(not isinstance(u, str) for u in urls):
            raise ValueError("Supply between 1 and 20 YouTube links.")
        urls = list(dict.fromkeys(youtube_source(url)["url"] for url in urls))
        with self.job_lock:
            if self.job["running"]:
                raise ValueError("Podcast processing is already running.")
            self.job = {"running": True, "items": [{**youtube_source(url), "status": "queued", "stage": "Queued"} for url in urls]}
        threading.Thread(target=self._ingest, args=(urls,), daemon=True).start()
        return {"accepted": True}

    def _ingest(self, urls):
        try:
            for index, url in enumerate(urls):
                def progress(stage):
                    with self.job_lock:
                        self.job["items"][index].update(status="processing", stage=stage)
                try:
                    progress("Starting")
                    with self.runtime_lock, closing(Store(self.database)) as store:
                        result = ingest(url, self.data_dir, store, self.embedder, progress=progress)
                    with self.job_lock:
                        self.job["items"][index].update(status="ready", stage="Ready", title=result["source"]["title"])
                except Exception as exc:
                    with self.job_lock:
                        self.job["items"][index].update(status="error", stage="Could not process this video", error=str(exc))
        finally:
            with self.job_lock:
                self.job["running"] = False

    def answer(self, question):
        load_settings()
        with self.runtime_lock, closing(Store(self.database)) as store:
            return ask(question, store, self.embedder, self.llm, translate=True)

    def search(self, question):
        if not isinstance(question, str) or not question.strip() or len(question) > 6000:
            raise ValueError("Enter a question of up to 6,000 characters.")
        load_settings()
        with self.runtime_lock, closing(Store(self.database)) as store:
            passages = store.search([question], self.embedder, limit=5)
            excerpts = [citation(p, p["words"][0]["index"], p["words"][-1]["index"]) for p in passages]
            if excerpts and os.getenv("OPENAI_API_KEY"):
                try:
                    excerpts = translate_citations(excerpts, store, self.llm)
                except Exception:
                    excerpts = [{**c, "translation_status": "unavailable"} for c in excerpts]
        return {"excerpts": excerpts}


def handler_for(demo: Demo):
    history = ResponseHistory(demo.data_dir / "responses.sqlite3")
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Keep questions and provider responses out of HTTP logs.
            pass

        def allowed_request(self):
            port = self.server.server_port
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in allowed:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin in {f"http://{host}" for host in allowed}

        def send_data(self, value, status=200):
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_body(body, "application/json; charset=utf-8", status)

        def send_body(self, body, content_type, status=200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https://i.ytimg.com; frame-src https://www.youtube-nocookie.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.allowed_request():
                self.send_data({"error": "This demo accepts local requests only."}, 403)
                return
            path = urlparse(self.path).path
            assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                      "/style.css": ("style.css", "text/css")}
            try:
                if path == "/api/status":
                    load_settings()
                    self.send_data(demo.status())
                elif path == "/api/videos" and hasattr(demo, "store"):
                    query = parse_qs(urlparse(self.path).query)
                    offset = int(query.get("offset", ["0"])[0])
                    if not 0 <= offset <= 1_000_000:
                        raise ValueError("Invalid page offset.")
                    self.send_data({"sources": demo.page(offset, status=query.get("status", [""])[0])})
                elif path == "/api/responses":
                    query = parse_qs(urlparse(self.path).query)
                    self.send_data(history.list(offset=int(query.get("offset", ["0"])[0])))
                elif path.startswith("/api/responses/"):
                    record = history.get(path.removeprefix("/api/responses/"))
                    self.send_data(record if record else {"error": "Saved response not found."}, 200 if record else 404)
                elif path in assets:
                    filename, kind = assets[path]
                    self.send_body((STATIC / filename).read_bytes(), kind + "; charset=utf-8")
                else:
                    self.send_data({"error": "Not found"}, 404)
            except ValueError as exc:
                self.send_data({"error": safe_error(exc)}, 400)
            except Exception as exc:
                self.send_data({"error": safe_error(exc)}, 500)

        def do_POST(self):
            if not self.allowed_request():
                self.send_data({"error": "This demo accepts local requests only."}, 403)
                return
            try:
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("Send a JSON request.")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 32768:
                    raise ValueError("Request must contain at most 32 KB of JSON.")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Request must be a JSON object.")
                path = urlparse(self.path).path
                load_settings()
                if getattr(demo, "read_only", False) and path in {
                    "/api/ingest", "/api/channels/preview", "/api/channels", "/api/channels/action"
                }:
                    self.send_data({"error": "This library contains only indexed Raj Shamani videos. Imports are disabled."}, 403)
                    return
                if path == "/api/ingest":
                    self.send_data(demo.start_ingestion(payload.get("urls")), 202)
                elif path == "/api/channels/preview":
                    self.send_data(demo.preview(payload.get("channel")))
                elif path == "/api/channels":
                    self.send_data(demo.add_channel(payload.get("channel_id")), 202)
                elif path == "/api/channels/action":
                    self.send_data(demo.action(payload.get("channel_id"), payload.get("action")))
                elif path == "/api/ask":
                    body, status = recorded_answer(demo, history, payload)
                    self.send_data(body, status)
                elif path == "/api/search":
                    if hasattr(demo, "store"):
                        self.send_data(demo.search(payload.get("question"), payload.get("source_id")))
                    else:
                        self.send_data(demo.search(payload.get("question")))
                else:
                    self.send_data({"error": "Not found"}, 404)
            except (ValueError, TypeError) as exc:
                self.send_data({"error": str(exc)}, 400)
            except Exception as exc:
                self.send_data({"error": safe_error(exc)}, 500)
    return Handler


def recorded_answer(demo, history, payload):
    started = time.monotonic()
    record = {"id": uuid4().hex, "created_at": datetime.now(timezone.utc).isoformat(),
              "question": payload.get("question") if isinstance(payload.get("question"), str) else "",
              "source_id": payload.get("source_id") if isinstance(payload.get("source_id"), str) else None,
              "backend": "supermemory" if hasattr(demo, "store") else "local",
              "model": demo.llm.model_name}
    try:
        if hasattr(demo, "store"):
            body = demo.answer(payload.get("question"), payload.get("source_id"))
        else:
            body = demo.answer(payload.get("question"))
        status = 200
    except Exception as exc:
        status = 400 if isinstance(exc, (ValueError, TypeError)) else 500
        body = {"error": safe_error(exc)}
        code = getattr(exc, "status_code", None)
        record["provider_http_status"] = code if isinstance(code, int) else None
        # Retain only the retry interval, never arbitrary provider headers or bodies.
        headers = getattr(getattr(exc, "response", None), "headers", {})
        retry_after = headers.get("retry-after") if headers else None
        if isinstance(retry_after, str):
            try:
                seconds = float(retry_after)
                if 0 <= seconds <= 604800:
                    record["retry_after_seconds"] = seconds
            except ValueError:
                pass
    body = {**body, "record_id": record["id"]}
    record.update(response=body, http_status=status, status=body.get("status", "error"),
                  elapsed_seconds=round(time.monotonic() - started, 3))
    try:
        history.save(record)
    except Exception:
        # Preserve the answer even if history storage fails, and make the failure visible.
        body.pop("record_id", None)
        body["recording_error"] = "This response could not be saved. Check available disk space and server permissions."
    return body, status


def safe_error(exc):
    status = getattr(exc, "status_code", None)
    if status == 429:
        body = getattr(exc, 'body', None)
        if isinstance(body, dict):
            detail = body.get('error', body)
            if isinstance(detail, dict) and detail.get('code') == 'insufficient_quota':
                return 'The OpenAI API account has insufficient quota. Check its API billing balance and usage limits.'
        return "The answer provider's usage limit was reached. Wait a minute, then try again."
    if status == 404:
        return "The configured answer model is unavailable. Check the server's model setting."
    if status in {401, 403}:
        return "The provider rejected access. Check the server's provider configuration."
    if isinstance(exc, ValueError):
        return str(exc)[:400]
    return "The request could not finish. Check connectivity and provider configuration, then retry."


def serve(data_dir: Path, links_file: Path, port=8000, backend="supermemory"):
    load_settings()
    if backend == "supermemory":
        from .raj_library import RajShamaniLibrary
        demo = RajShamaniLibrary(data_dir)
    else:
        demo = Demo(data_dir, links_file)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_for(demo))
    try:
        if backend == "supermemory":
            demo.start()
        print(f"Knowledge Retriever: http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if backend == "supermemory":
            demo.close()
