"""Read workspace directories and manage the cached file tree."""

import ntpath
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypedDict
from uuid import uuid4

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


class FileTreeItem(TypedDict):
    name: str
    is_directory: bool
    modified_time: float | None


def scan_dir(folder: Path, include_modified: bool = False) -> list[FileTreeItem]:
    """Read one directory without recursively scanning its children."""
    # Read metadata only for date sorting: stat calls can add substantial I/O in large directories. Children are scanned separately when opened.
    with os.scandir(folder) as entries:
        return [
            {
                "name": entry.name,
                "is_directory": entry.is_dir(follow_symlinks=False),
                "modified_time": entry.stat(follow_symlinks=False).st_mtime
                if include_modified
                else None,
            }
            for entry in entries
        ]


def sort_items(items: list[FileTreeItem], sort_mode: str) -> list[FileTreeItem]:
    if sort_mode == "alphabetic":
        return sorted(items, key=lambda item: item["name"].casefold())
    if sort_mode == "modified":
        return sorted(
            items,
            key=lambda item: item["modified_time"] or 0,
            reverse=True,
        )
    raise ValueError(f"Unknown sort mode: {sort_mode}")


OPEN_DELAY = 0.2
CLOSED_DELAY = 5.0
SCAN_WORKERS = 2


class DirectorySnapshot(TypedDict):
    workspace_id: str
    path: str
    items: list[FileTreeItem] | None
    loading: bool
    stale: bool
    error: str | None


class TreeSnapshot(TypedDict):
    workspace_id: str
    revision: int
    directories: list[DirectorySnapshot]
    watcher_error: str | None


@dataclass
class Directory:
    # A cached list stays available while stale or loading. version tracks invalidations so an in-flight scan cannot overwrite newer changes.
    items: list[FileTreeItem] | None = None
    stale: bool = True
    visible: bool = False
    loading: bool = False
    version: int = 0
    deadline: float | None = None
    error: str | None = None
    modified_metadata: bool = False


class ChangeHandler(FileSystemEventHandler):
    def __init__(self, tree: "FileTree") -> None:
        self.tree = tree

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type in ("opened", "closed", "closed_no_write"):
            return
        # Overflow support differs between watchdog releases and platforms.
        if "overflow" in event.event_type or "lost" in event.event_type:
            self.tree.invalidate_all("File watcher lost events; refresh required")
            return
        # Notify the note separately so content edits do not fetch the whole tree.
        if not event.is_directory:
            for path in (event.src_path, event.dest_path):
                if path:
                    self.tree._note_changed(Path(os.fsdecode(path)))
        if event.event_type == "modified" and not event.is_directory:
            if not self.tree.uses_modified_sort():
                return
        for path in (event.src_path, event.dest_path):
            if path:
                self.tree.path_changed(
                    Path(os.fsdecode(path)),
                    invalidate_descendants=event.event_type in ("moved", "deleted"),
                )


class FileTree:
    """Own a workspace cache and serialize updates from watcher and scans."""

    def __init__(
        self,
        root: Path,
        notify: Callable[[], None],
        notify_note: Callable[[Path], None] | None = None,
    ) -> None:
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise NotADirectoryError(str(root))
        self.workspace_id = uuid4().hex
        self._notify = notify
        self._note_changed: Callable[[Path], None] = notify_note or (lambda _path: None)
        self._condition = threading.Condition(threading.RLock())
        self._directories: dict[str, Directory] = {}
        self._revision = 0
        self._sort_mode = "alphabetic"
        self._closed = False
        self._watcher_error: str | None = None
        self._observer = Observer()
        self._workers: list[threading.Thread] = []
        try:
            self._observer.schedule(ChangeHandler(self), str(self.root), recursive=True)
            self._observer.start()
        except OSError as error:
            self._watcher_error = str(error)
        for index in range(SCAN_WORKERS):
            worker = threading.Thread(
                target=self._work, name=f"file-tree-{index}", daemon=True
            )
            worker.start()
            self._workers.append(worker)

    def _path(self, relative: str) -> tuple[str, Path]:
        if not isinstance(relative, str):
            raise TypeError("Directory path must be a string")
        path = Path(relative)
        if path.anchor or ".." in path.parts:
            raise ValueError("Directory must stay inside the workspace")
        # Resolving also catches symlinks that lead outside the workspace.
        resolved = (self.root / path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as error:
            raise ValueError("Directory must stay inside the workspace") from error
        return path.as_posix() if path.parts else "", resolved

    def create_entry(self, directory: str, name: str, is_directory: bool) -> str:
        """Create one child without replacing an existing file or directory."""
        if not isinstance(name, str) or not name or name in (".", ".."):
            raise ValueError("A file or folder name is required")
        if (
            any(char in name for char in '/\\<>:"|?*')
            or any(ord(char) < 32 for char in name)
            or name.endswith((" ", "."))
            or ntpath.isreserved(name)
        ):
            raise ValueError("Invalid file or folder name")
        if not isinstance(is_directory, bool):
            raise TypeError("is_directory must be a boolean")
        key, parent = self._path(directory)
        target = parent / name
        # Exclusive creation makes an existing name an error instead of overwriting it.
        if is_directory:
            target.mkdir()
        else:
            with target.open("x", encoding="utf-8"):
                pass
        self.refresh(key)
        return f"{key}/{name}" if key else name

    def _changed(self) -> None:
        self._revision += 1
        self._condition.notify_all()

    def _signal(self) -> None:
        try:
            self._notify()
        except Exception:
            # A notification is only a wake-up; snapshots remain authoritative.
            pass

    def uses_modified_sort(self) -> bool:
        with self._condition:
            return self._sort_mode == "modified"

    def set_sort(self, sort_mode: str) -> None:
        if sort_mode not in ("alphabetic", "modified"):
            raise ValueError(f"Unknown sort mode: {sort_mode}")
        with self._condition:
            self._sort_mode = sort_mode
            for directory in self._directories.values():
                if sort_mode == "modified" and not directory.modified_metadata:
                    directory.stale = True
                    directory.version += 1
                    directory.deadline = (
                        time.monotonic()
                        if directory.visible
                        else time.monotonic() + CLOSED_DELAY
                    )
            self._changed()
        self._signal()

    def set_visible(self, relative: str, visible: bool) -> None:
        key, _ = self._path(relative)
        if not isinstance(visible, bool):
            raise TypeError("visible must be a boolean")
        with self._condition:
            directory = self._directories.get(key)
            if directory is None:
                if not visible:
                    return
                directory = self._directories[key] = Directory()
            directory.visible = visible
            if visible and directory.stale and not directory.loading:
                directory.error = None
                directory.deadline = time.monotonic()
            self._changed()
        self._signal()

    def refresh(self, relative: str | None = None) -> None:
        key = self._path(relative)[0] if relative is not None else None
        with self._condition:
            targets = (
                self._directories.items()
                if key is None
                else [(key, self._directories.setdefault(key, Directory()))]
            )
            for _, directory in targets:
                directory.stale = True
                directory.error = None
                directory.version += 1
                directory.deadline = (
                    time.monotonic()
                    if directory.visible
                    else time.monotonic() + CLOSED_DELAY
                )
            self._changed()
        self._signal()

    def invalidate_all(self, error: str) -> None:
        with self._condition:
            self._watcher_error = error
        self.refresh()

    def path_changed(self, path: Path, invalidate_descendants: bool = False) -> None:
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            return
        parent = relative.parent.as_posix()
        key = "" if parent == "." else parent
        with self._condition:
            if self._closed:
                return
            changed_path = relative.as_posix()
            # Only cached directories need work. A moved or deleted folder can also invalidate cached lists anywhere beneath its old path.
            targets = [key]
            if invalidate_descendants:
                targets.extend(
                    name
                    for name in self._directories
                    if name == changed_path or name.startswith(changed_path + "/")
                )
            changed = False
            status_changed = False
            for name in set(targets):
                directory = self._directories.get(name)
                if directory is None:
                    continue
                changed = True
                status_changed = (
                    status_changed or not directory.stale or directory.error is not None
                )
                directory.version += 1
                directory.stale = True
                directory.error = None
                deadline = time.monotonic() + (
                    OPEN_DELAY if directory.visible else CLOSED_DELAY
                )
                # Keep the earliest deadline: a stream of events cannot postpone refresh indefinitely. Visible folders wait less.
                directory.deadline = (
                    min(directory.deadline, deadline)
                    if directory.deadline is not None
                    else deadline
                )
            if not changed:
                return
            if status_changed:
                self._changed()
            else:
                self._condition.notify_all()
        if status_changed:
            self._signal()

    def snapshot(self) -> TreeSnapshot:
        # Snapshots contain all loaded directories, sorted on each request. This keeps the cache independent of sort order, at the cost of repeated sorting and larger bridge payloads as the tree grows.
        with self._condition:
            directories: list[DirectorySnapshot] = []
            for path, directory in self._directories.items():
                items = directory.items
                if items is not None:
                    items = sort_items(items, self._sort_mode)
                directories.append(
                    {
                        "workspace_id": self.workspace_id,
                        "path": path,
                        "items": items,
                        "loading": directory.loading or directory.deadline is not None,
                        "stale": directory.stale,
                        "error": directory.error,
                    }
                )
            return {
                "workspace_id": self.workspace_id,
                "revision": self._revision,
                "directories": directories,
                "watcher_error": self._watcher_error,
            }

    def _work(self) -> None:
        # Workers claim one directory under the condition lock, then scan without holding it so watcher events and other calls can proceed.
        while True:
            with self._condition:
                while True:
                    if self._closed:
                        return
                    now = time.monotonic()
                    ready = [
                        (key, directory)
                        for key, directory in self._directories.items()
                        if directory.deadline is not None
                        and directory.deadline <= now
                        and not directory.loading
                    ]
                    if ready:
                        # Among scans whose deadlines have passed, prefer visible directories and then the earliest deadline.
                        key, directory = min(
                            ready,
                            key=lambda pair: (
                                not pair[1].visible,
                                pair[1].deadline or 0,
                            ),
                        )
                        directory.deadline = None
                        directory.loading = True
                        version = directory.version
                        include_modified = self._sort_mode == "modified"
                        self._changed()
                        break
                    deadlines = [
                        d.deadline
                        for d in self._directories.values()
                        if d.deadline is not None and not d.loading
                    ]
                    timeout = max(0, min(deadlines) - now) if deadlines else 1.0
                    self._condition.wait(min(timeout, 1.0))
                    if (
                        self._observer.ident is not None
                        and (
                            not self._observer.is_alive()
                            or any(
                                not emitter.is_alive()
                                for emitter in self._observer.emitters
                            )
                        )
                        and self._watcher_error is None
                    ):
                        self._watcher_error = "File watcher stopped unexpectedly"
                        for d in self._directories.values():
                            d.stale = True
                            d.version += 1
                        self._changed()
                        self._signal()
            self._signal()
            try:
                _, path = self._path(key)
                items = scan_dir(path, include_modified)
                error = None
            except (OSError, ValueError) as exc:
                items = None
                error = str(exc)
            with self._condition:
                if self._closed:
                    return
                directory.loading = False
                # A change during the scan, or a switch to date sorting, makes its result unreliable. Schedule another scan instead.
                if version != directory.version or (
                    self._sort_mode == "modified" and not include_modified
                ):
                    directory.deadline = time.monotonic() + OPEN_DELAY
                elif error is not None:
                    directory.error = error
                    directory.stale = True
                else:
                    directory.items = items
                    directory.modified_metadata = include_modified
                    directory.stale = False
                    directory.error = None
                self._changed()
            self._signal()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        if self._observer.ident is not None:
            self._observer.stop()
            self._observer.join(timeout=3)
        for worker in self._workers:
            worker.join(timeout=3)
