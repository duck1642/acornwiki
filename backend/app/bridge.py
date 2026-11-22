"""Translate PyWebView API calls into backend operations."""

import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from backend.app.settings import SETTINGS_PATH, load_settings, save_settings
from backend.app.workspace import load_workspace_settings
from backend.modules.notes import (
    NoteSnapshot,
    note_path,
    read_note,
    resolve_note_link,
    save_note,
)
from backend.services.filesystem import FileTree, TreeSnapshot


class SharedState(Protocol):
    def __setitem__(self, key: str, value: int, /) -> None: ...


class Window(Protocol):
    state: SharedState

    def destroy(self) -> None: ...


class Bridge:
    """Expose backend operations to the frontend through PyWebView."""

    def __init__(self) -> None:
        self._tree: FileTree | None = None
        self._lock = threading.RLock()
        self._window: Window | None = None
        self._signal_event = threading.Event()
        self._signal_lock = threading.Lock()
        self._tree_pending = False
        self._note_pending = False
        self._active_note: str | None = None
        self._stopped = False
        self._allow_close = False
        self._close_requested = False
        self._revision = 0
        self._media_url = ""
        self._notifier = threading.Thread(target=self._notify_loop, daemon=True)
        self._notifier.start()

    def _attach_window(self, window: Window) -> None:
        self._window = window

    def _notify_loop(self) -> None:
        # Event coalesces pending signals. The revision is only a wake-up: the frontend fetches the authoritative snapshot through the bridge.
        while True:
            self._signal_event.wait()
            with self._signal_lock:
                self._signal_event.clear()
                tree_pending, self._tree_pending = self._tree_pending, False
                note_pending, self._note_pending = self._note_pending, False
                close_requested, self._close_requested = self._close_requested, False
            if self._stopped:
                return
            window = self._window
            if window is not None:
                self._revision += 1
                try:
                    if tree_pending:
                        window.state["file_tree_revision"] = self._revision
                    if note_pending:
                        window.state["note_revision"] = self._revision
                    if close_requested:
                        window.state["close_request"] = self._revision
                except Exception:
                    # The frontend resynchronizes after reload and focus changes.
                    pass

    def ping(self) -> str:
        return "Backend is working."

    def _request_close(self) -> bool:
        """Cancel native closing until the frontend resolves unsaved edits."""
        if self._allow_close:
            return True
        with self._signal_lock:
            self._close_requested = True
            self._signal_event.set()
        return False

    def _tree_changed(self) -> None:
        with self._signal_lock:
            self._tree_pending = True
            self._signal_event.set()

    def _note_changed(self, path: Path) -> None:
        # Compare normalized names without opening every changed file.
        if os.path.normcase(os.path.abspath(path)) != self._active_note:
            return
        with self._signal_lock:
            self._note_pending = True
            self._signal_event.set()

    def finish_close(self) -> None:
        """Close the window after the editor has approved the request."""
        self._allow_close = True
        if self._window is not None:
            self._window.destroy()

    def get_settings(self) -> dict[str, object]:
        with self._lock:
            return load_settings(SETTINGS_PATH)

    def set_editor_preference(self, name: str, value: bool) -> None:
        """Update one editor preference without replacing workspace choices."""
        if name not in ("autosave", "auto_reload", "reload_notice"):
            raise ValueError("Unknown editor preference")
        if not isinstance(value, bool):
            raise TypeError("Editor preference must be a boolean")
        with self._lock:
            settings = load_settings(SETTINGS_PATH)
            editor = settings["editor"]
            if not isinstance(editor, dict):
                raise ValueError("Invalid editor preferences")
            editor[name] = value
            save_settings(SETTINGS_PATH, settings)

    def get_workspace_settings(self, workspace_root: str) -> dict[str, object]:
        if not isinstance(workspace_root, str) or not workspace_root.strip():
            raise ValueError("workspace_root must be a non-empty path string")
        return load_workspace_settings(Path(workspace_root))

    def open_workspace(self, workspace_root: str) -> TreeSnapshot:
        if not isinstance(workspace_root, str) or not workspace_root.strip():
            raise ValueError("workspace_root must be a non-empty path string")
        with self._lock:
            if self._tree is not None:
                self._tree.close()
                self._tree = None
            self._active_note = None
            self._tree = FileTree(Path(workspace_root), self._tree_changed, self._note_changed)
            self._tree.set_visible("", True)
            return self._tree.snapshot()

    def _require_tree(self, workspace_id: str) -> FileTree:
        if not isinstance(workspace_id, str):
            raise TypeError("workspace_id must be a string")
        # Reject calls belonging to a workspace that has since been replaced.
        tree = self._tree
        if tree is None or tree.workspace_id != workspace_id:
            raise ValueError("Workspace is no longer active")
        return tree

    def get_tree(self, workspace_id: str) -> TreeSnapshot:
        with self._lock:
            return self._require_tree(workspace_id).snapshot()

    def read_note(self, workspace_id: str, path: str) -> NoteSnapshot:
        with self._lock:
            return read_note(self._require_tree(workspace_id).root, path)

    def resolve_note_link(
        self, workspace_id: str, note: str, href: str
    ) -> dict[str, str]:
        """Resolve a Markdown note link without opening it or discarding edits."""
        with self._lock:
            root = self._require_tree(workspace_id).root
            path, fragment = resolve_note_link(root, note, href)
            return {"path": path, "fragment": fragment}

    def open_local_file(self, workspace_id: str, note: str, href: str) -> bool:
        """Open an existing workspace file with the operating system's default app."""
        with self._lock:
            root = self._require_tree(workspace_id).root
            path, fragment = resolve_note_link(root, note, href)
            if fragment:
                raise ValueError("File fragments are not supported")
            return self.open_workspace_file(workspace_id, path)

    def _workspace_file(self, workspace_id: str, path: str) -> Path:
        """Validate a workspace-relative file path before a shell operation."""
        if not isinstance(path, str) or not path or Path(path).anchor:
            raise ValueError("Expected a workspace-relative path")
        root = self._require_tree(workspace_id).root.resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise ValueError("File must stay inside the workspace")
        if not target.is_file():
            raise FileNotFoundError("Linked file does not exist")
        return target

    def open_workspace_file(self, workspace_id: str, path: str) -> bool:
        """Open an allowed file or report that its extension is blocked."""
        with self._lock:
            target = self._workspace_file(workspace_id, path)
            blocked = load_settings(SETTINGS_PATH)["blocked_extensions"]
            if not isinstance(blocked, list):
                raise ValueError("Invalid blocked extensions")
            blocked_items: list[object] = blocked
            if target.suffix.lower() in (ext.lower() for ext in blocked_items if isinstance(ext, str)):
                return False
            if sys.platform == "win32":
                os.startfile(target)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
            return True

    def reveal_workspace_file(self, workspace_id: str, path: str) -> None:
        """Show a workspace file in the file manager without opening it."""
        with self._lock:
            target = self._workspace_file(workspace_id, path)
            if sys.platform == "win32":
                subprocess.Popen(["explorer.exe", "/select,", str(target)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target.parent)])

    def set_blocked_extensions(self, extensions: list[str]) -> None:
        """Save the user-editable list of file extensions blocked from opening."""
        if not isinstance(extensions, list) or any(not isinstance(x, str) for x in extensions):
            raise ValueError("Expected a list of extensions")
        with self._lock:
            settings = load_settings(SETTINGS_PATH)
            settings["blocked_extensions"] = list(dict.fromkeys(x.strip().lower() for x in extensions))
            save_settings(SETTINGS_PATH, settings)

    def media_url(self, workspace_id: str) -> str:
        """Return the local image endpoint for the active workspace."""
        with self._lock:
            self._require_tree(workspace_id)
            return self._media_url

    def open_external_link(self, url: str) -> None:
        """Open an ordinary web link in the user's default browser."""
        if not isinstance(url, str) or urlsplit(url).scheme.lower() not in (
            "http", "https"
        ):
            raise ValueError("Only HTTP and HTTPS links are supported")
        webbrowser.open(url)

    def _resolve_media(self, workspace_id: str, note: str, href: str) -> Path:
        with self._lock:
            root = self._require_tree(workspace_id).root
            path, fragment = resolve_note_link(root, note, href)
            if fragment:
                raise ValueError("Image fragments are not supported")
            return root / path

    def set_active_note(self, workspace_id: str, path: str) -> None:
        """Watch the note only after the frontend accepts its open result."""
        with self._lock:
            root = self._require_tree(workspace_id).root
            self._active_note = os.path.normcase(os.path.abspath(note_path(root, path)))

    def save_note(
        self, workspace_id: str, path: str, content: str, version: str
    ) -> NoteSnapshot:
        with self._lock:
            return save_note(
                self._require_tree(workspace_id).root, path, content, version
            )

    def set_directory_visible(
        self, workspace_id: str, path: str, visible: bool
    ) -> TreeSnapshot:
        with self._lock:
            tree = self._require_tree(workspace_id)
            tree.set_visible(path, visible)
            return tree.snapshot()

    def set_tree_sort(self, workspace_id: str, sort_mode: str) -> TreeSnapshot:
        with self._lock:
            tree = self._require_tree(workspace_id)
            tree.set_sort(sort_mode)
            return tree.snapshot()

    def refresh_tree(self, workspace_id: str, path: str | None = None) -> TreeSnapshot:
        with self._lock:
            tree = self._require_tree(workspace_id)
            tree.refresh(path)
            return tree.snapshot()

    def close_workspace(self, workspace_id: str) -> None:
        with self._lock:
            tree = self._require_tree(workspace_id)
            self._tree = None
            self._active_note = None
            tree.close()

    def _close(self) -> None:
        with self._lock:
            tree = self._tree
            self._tree = None
            if tree is not None:
                tree.close()
        self._stopped = True
        self._signal_event.set()
        self._notifier.join(timeout=3)
