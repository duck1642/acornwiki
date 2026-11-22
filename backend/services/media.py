"""Serve workspace images to the WebView through a local HTTP address."""

import secrets
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlsplit

IMAGE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".avif": "image/avif",
    ".svg": "image/svg+xml",
}


class MediaServer:
    """Serve only supported images resolved by the active workspace."""

    def __init__(self, resolve: Callable[[str, str, str], Path]) -> None:
        token = secrets.token_urlsafe(32)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parts = urlsplit(self.path)
                if parts.path != f"/{token}/image":
                    self.send_error(404)
                    return
                params = parse_qs(parts.query)
                try:
                    workspace, note, src = (
                        params[key][0] for key in ("workspace", "note", "src")
                    )
                    path = resolve(workspace, note, src)
                    content_type = IMAGE_TYPES[path.suffix.lower()]
                    image = path.open("rb")
                except (KeyError, IndexError, ValueError, OSError):
                    self.send_error(404)
                    return
                with image:
                    try:
                        self.send_response(200)
                        self.send_header("Content-Type", content_type)
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.send_header(
                            "Content-Security-Policy", "default-src 'none'; sandbox"
                        )
                        self.send_header("Cache-Control", "no-store")
                        self.end_headers()
                        shutil.copyfileobj(image, self.wfile)
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        # A cancelled image request cannot receive another response.
                        pass

            def log_message(self, format: str, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.url = f"http://127.0.0.1:{self._server.server_port}/{token}/image"

    def close(self) -> None:
        """Stop the server and release its local port."""
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
