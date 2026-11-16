"""Translate PyWebView API calls into backend operations."""

import threading
from pathlib import Path
from typing import Protocol

from backend.app.settings import SETTINGS_PATH, load_settings
from backend.app.workspace import load_workspace_settings
from backend.services.filesystem import FileTree, TreeSnapshot


class SharedState(Protocol):
    def __setitem__(self, key: str, value: int) -> None: ...


class Window(Protocol):
    state: SharedState


class Bridge:
    """Expose backend operations to the frontend through PyWebView."""

    def __init__(self) -> None:
        self._tree: FileTree | None = None
        self._lock = threading.RLock()
        self._window: Window | None = None
        self._signal_event = threading.Event()
        self._stopped = False
        self._revision = 0
        self._notifier = threading.Thread(target=self._notify_loop, daemon=True)
        self._notifier.start()

    def _attach_window(self, window: Window) -> None:
        self._window = window

    def _notify_loop(self) -> None:
        while True:
            self._signal_event.wait()
            self._signal_event.clear()
            if self._stopped:
                return
            window = self._window
            if window is not None:
                self._revision += 1
                try:
                    window.state["file_tree_revision"] = self._revision
                except Exception:
                    # The frontend resynchronizes after reload and focus changes.
                    pass

    def ping(self) -> str:
        return "Backend çalışıyor"

    def get_settings(self) -> dict[str, object]:
        return load_settings(SETTINGS_PATH)

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
            self._tree = FileTree(Path(workspace_root), self._signal_event.set)
            self._tree.set_visible("", True)
            return self._tree.snapshot()

    def _require_tree(self, workspace_id: str) -> FileTree:
        if not isinstance(workspace_id, str):
            raise TypeError("workspace_id must be a string")
        tree = self._tree
        if tree is None or tree.workspace_id != workspace_id:
            raise ValueError("Workspace is no longer active")
        return tree

    def get_tree(self, workspace_id: str) -> TreeSnapshot:
        with self._lock:
            return self._require_tree(workspace_id).snapshot()

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
