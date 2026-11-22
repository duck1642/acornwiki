"""Start the development frontend and open the desktop window."""

import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import webview

from backend.app.bridge import Bridge
from backend.services.media import MediaServer


def available_port() -> int:
    """Choose an available local port for the development server."""
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def wait_for_vite(process: subprocess.Popen[bytes], address: str) -> None:
    """Wait until Vite responds or report a startup failure."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Vite stopped before it was ready")

        try:
            with urlopen(f"{address}/@vite/client", timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError):
            time.sleep(0.2)

    raise TimeoutError("Vite did not become ready within 30 seconds")


def main() -> None:
    frontend_dir = Path(__file__).resolve().parent / "frontend"
    vite_script = frontend_dir / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite_script.is_file():
        raise FileNotFoundError("Vite is missing; install the frontend dependencies")

    port = available_port()
    address = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            "node",
            str(vite_script),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--strictPort",
        ],
        cwd=frontend_dir,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )

    bridge = Bridge()
    media = MediaServer(bridge._resolve_media)
    bridge._media_url = media.url
    try:
        wait_for_vite(process, address)
        print(f"Vite is ready: {address}")
        # PyWebView's create_window signature has incomplete type information.
        window = webview.create_window(  # pyright: ignore[reportUnknownMemberType]
            "acornwiki", address, js_api=bridge
        )
        if window is None:
            raise RuntimeError("PyWebView window could not be created")
        # PyWebView types Window.state as a property rather than its state object.
        bridge._attach_window(window)  # pyright: ignore[reportArgumentType]
        window.events.closing += bridge._request_close
        webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
        webview.start(debug=True)
    finally:
        media.close()
        bridge._close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
