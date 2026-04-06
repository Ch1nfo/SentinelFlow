#!/usr/bin/env python3
"""Serve the built WebUI bundle with SPA fallback."""

from __future__ import annotations

import argparse
import posixpath
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


def resolve_request_path(root: Path, request_path: str) -> Path:
    parsed_path = urlsplit(request_path).path or "/"
    normalized = posixpath.normpath(unquote(parsed_path))
    relative_path = normalized.lstrip("/")
    candidate = (root / relative_path).resolve()

    if candidate != root and root not in candidate.parents:
        return root / "index.html"

    if candidate.is_dir():
        index_file = candidate / "index.html"
        if index_file.exists():
            return index_file

    if candidate.exists():
        return candidate

    if Path(relative_path).suffix:
        return candidate

    return root / "index.html"


class SPARequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str | None = None, **kwargs):
        self.root = Path(directory or ".").resolve()
        super().__init__(*args, directory=str(self.root), **kwargs)

    def translate_path(self, path: str) -> str:
        return str(resolve_request_path(self.root, path))


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve built SentinelFlow WebUI assets.")
    parser.add_argument("--directory", required=True, help="Directory containing the built WebUI.")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind.")
    parser.add_argument("--port", type=int, default=5173, help="Port to bind.")
    args = parser.parse_args()

    root = Path(args.directory).resolve()
    index_file = root / "index.html"
    if not index_file.exists():
        raise SystemExit(f"WebUI build artifact not found: {index_file}")

    handler = lambda *handler_args, **handler_kwargs: SPARequestHandler(  # noqa: E731
        *handler_args,
        directory=str(root),
        **handler_kwargs,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
