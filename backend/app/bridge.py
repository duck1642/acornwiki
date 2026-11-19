"""Translate PyWebView API calls into backend operations."""

import os
import threading
from pathlib import Path
from typing import Protocol

from backend.app.settings import SETTINGS_PATH, load_settings, save_settings
from backend.app.workspace import load_workspace_settings
from backend.modules.notes import NoteSnapshot, note_path, read_note, save_note
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
