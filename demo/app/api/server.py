"""Minimal HTTP server: JSON API plus the static web page. Standard library only."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.api import handlers
from app.config import DATA_FILE, SERVER_PORT
from app.repository import JsonFileRepository

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


def make_handler(services: handlers.Services):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: object) -> None:
            self._send(status, json.dumps(data).encode("utf-8"), "application/json; charset=utf-8")

        def _dispatch(self, method: str) -> None:
            url = urlparse(self.path)
            query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            try:
                if method == "GET" and url.path == "/api/transactions":
                    return self._json(200, handlers.list_transactions(services, query))
                if method == "POST" and url.path == "/api/transactions":
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    return self._json(201, handlers.create_transaction(services, payload))
                if method == "GET" and url.path == "/api/report":
                    return self._json(200, handlers.monthly_report(services, query))
                if method == "GET" and url.path == "/api/export":
                    return self._send(200, handlers.export_csv(services, query).encode("utf-8"), "text/csv; charset=utf-8")
                if method == "GET" and url.path in ("/", "/index.html", "/app.js"):
                    name = "index.html" if url.path == "/" else url.path.lstrip("/")
                    body = (WEB_DIR / name).read_bytes()
                    return self._send(200, body, "text/html; charset=utf-8" if name.endswith(".html") else "application/javascript")
            except handlers.ApiError as exc:
                return self._json(exc.status, {"errors": exc.errors})
            except (ValueError, OSError) as exc:
                return self._json(400, {"errors": [str(exc)]})
            self._json(404, {"errors": ["not found"]})

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - quiet server
            return None

    return Handler


def serve(port: int = SERVER_PORT, data_file: str = DATA_FILE) -> ThreadingHTTPServer:
    services = handlers.Services(JsonFileRepository(data_file))
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(services))
    return server


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    port = int(argv[0]) if argv else SERVER_PORT
    server = serve(port)
    print(f"ledger demo on http://127.0.0.1:{port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
