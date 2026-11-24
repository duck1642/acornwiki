"""Translate PyWebView API calls into backend operations."""

import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Protocol, TypedDict
from urllib.parse import urlsplit

from backend.app.settings import SETTINGS_PATH, load_settings, save_settings
from backend.app.workspace import (
    load_workspace_settings,
    save_workspace_settings,
    update_workspace_appearance,
)
from backend.modules.link_paths import path_after_move, resolve_moved_targets
from backend.modules.notes import (
    NoteBatch,
    NoteConflictError,
    NoteSnapshot,
    NoteVersion,
    TextFileReadResult,
    TextFileSnapshot,
    list_markdown_notes,
    markdown_name,
    note_path,
    read_note,
    read_note_batch,
    read_text_file,
    resolve_note_link,
    save_note,
    save_text_file,
    validate_note_rewrites,
    validate_note_scan,
    workspace_file_path,
)
from backend.services.filesystem import FileTree, TreeSnapshot


class SharedState(Protocol):
    def __setitem__(self, key: str, value: int, /) -> None: ...


class Window(Protocol):
    state: SharedState

    def destroy(self) -> None: ...


class NoteTargets(TypedDict):
    path: str
    targets: list[str]


class MoveFailure(TypedDict):
    path: str
    error: str


class MoveResult(TypedDict):
    destination: str
    updated: list[str]
    failures: list[MoveFailure]


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
        self._open_notes: set[str] = set()
        self._open_notes_registered = False
        self._active_note: str | None = None
        self._stopped = False
        self._allow_close = False
        self._close_requested = False
        self._revision = 0
        self._media_url = ""
        self._search_generation = 0
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
        changed_note = os.path.normcase(os.path.abspath(path))
        watched = (
            changed_note in self._open_notes
            if self._open_notes_registered
            else changed_note == self._active_note
        )
        if not watched:
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

    def set_workspace_appearance(self, workspace_id: str, appearance: object) -> None:
        """Update appearance settings for the currently active workspace."""
        with self._lock:
            tree = self._require_tree(workspace_id)
            update_workspace_appearance(tree.root, appearance)

    def set_new_items_folder(self, workspace_id: str, folder: str) -> None:
        """Save an existing workspace-relative default folder for new items."""
        if not isinstance(folder, str) or not folder.strip():
            raise ValueError("A workspace-relative folder is required")
        with self._lock:
            tree = self._require_tree(workspace_id)
            settings = load_workspace_settings(tree.root)
            settings["new_notes_folder"] = folder.strip()
            target = (tree.root / folder.strip()).resolve(strict=True)
            if not target.is_relative_to(tree.root) or not target.is_dir():
                raise ValueError("Folder must be inside the workspace")
            save_workspace_settings(tree.root, settings)

    def search_workspace(self, workspace_id: str, query: str) -> dict[str, object]:
        """Search names without blocking other bridge calls; stop older searches."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("A search term is required")
        with self._lock:
            tree = self._require_tree(workspace_id)
            self._search_generation += 1
            generation = self._search_generation
        results: list[dict[str, object]] = []
        errors: list[str] = []

        def on_error(error: OSError) -> None:
            errors.append(str(error))

        for directory, folders, files in os.walk(
            tree.root, followlinks=False, onerror=on_error
        ):
            if generation != self._search_generation or tree is not self._tree:
                return {"items": [], "truncated": False, "error": None}
            parent = Path(directory)
            folders[:] = [
                name for name in folders
                if not (parent / name).is_symlink() and not (parent / name).is_junction()
            ]
            for entries, is_directory in ((folders, True), (files, False)):
                for name in entries:
                    if query.casefold() not in name.casefold():
                        continue
                    results.append({
                        "path": (parent / name).relative_to(tree.root).as_posix(),
                        "is_directory": is_directory,
                    })
                    if len(results) >= 500:
                        return {
                            "items": results, "truncated": True,
                            "error": errors[0] if errors else None,
                        }
        return {"items": results, "truncated": False, "error": errors[0] if errors else None}

    def open_workspace(self, workspace_root: str) -> TreeSnapshot:
        if not isinstance(workspace_root, str) or not workspace_root.strip():
            raise ValueError("workspace_root must be a non-empty path string")
        with self._lock:
            if self._tree is not None:
                self._tree.close()
                self._tree = None
            self._open_notes = set()
            self._open_notes_registered = False
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

    def read_text_file(self, workspace_id: str, path: str) -> TextFileReadResult:
        with self._lock:
            return read_text_file(self._require_tree(workspace_id).root, path)

    def list_plan_notes(self, workspace_id: str) -> list[str]:
        """List Markdown files to inspect while planning a move."""
        with self._lock:
            return list_markdown_notes(self._require_tree(workspace_id).root)

    def read_plan_notes(
        self, workspace_id: str, paths: list[str], start: int, max_bytes: int, max_notes: int
    ) -> NoteBatch:
        """Read the next bounded group of note snapshots for move planning."""
        with self._lock:
            root = self._require_tree(workspace_id).root
            return read_note_batch(root, paths, start, max_bytes, max_notes)

    def create_note(self, workspace_id: str, directory: str, name: str) -> str:
        """Create an empty Markdown note in the active workspace."""
        with self._lock:
            return self._require_tree(workspace_id).create_entry(
                directory, markdown_name(name), False
            )

    def create_directory(self, workspace_id: str, directory: str, name: str) -> str:
        """Create one folder in the active workspace."""
        with self._lock:
            return self._require_tree(workspace_id).create_entry(directory, name, True)

    def plan_link_targets(
        self,
        workspace_id: str,
        note: str,
        source: str,
        destination: str,
        targets: list[str],
    ) -> list[str | None]:
        """Calculate replacement link targets without modifying the workspace."""
        with self._lock:
            root = self._require_tree(workspace_id).root
            return resolve_moved_targets(root, note, source, destination, targets)

    def plan_link_targets_batch(
        self, workspace_id: str, source: str, destination: str, notes: list[NoteTargets]
    ) -> list[list[str | None]]:
        """Calculate target changes for a bounded group of Markdown notes."""
        if not isinstance(notes, list) or len(notes) > 100:
            raise ValueError("Expected at most 100 notes")
        if any(
            not isinstance(note, dict)
            or not isinstance(note.get("path"), str)
            or not isinstance(note.get("targets"), list)
            or not all(isinstance(target, str) for target in note["targets"])
            for note in notes
        ):
            raise ValueError("Invalid note targets")
        with self._lock:
            root = self._require_tree(workspace_id).root
            return [
                resolve_moved_targets(root, note["path"], source, destination, note["targets"])
                for note in notes
            ]

    def validate_link_plan(
        self,
        workspace_id: str,
        snapshots: list[NoteVersion],
        rewrites: list[NoteSnapshot],
    ) -> None:
        """Check a plan against the workspace without moving or writing files."""
        with self._lock:
            root = self._require_tree(workspace_id).root
            versions = validate_note_scan(root, snapshots)
            validate_note_rewrites(root, rewrites, versions)

    def commit_move(
        self,
        workspace_id: str,
        source: str,
        destination: str,
        snapshots: list[NoteVersion] | None,
        rewrites: list[NoteSnapshot],
    ) -> MoveResult:
        """Move one entry, then save the planned rewrites at their new paths."""
        with self._lock:
            tree = self._require_tree(workspace_id)
            source_path, destination_path, is_directory = tree.validate_move_entry(
                source, destination
            )
            if source == destination:
                raise ValueError("Choose a different destination")
            if (
                not is_directory
                and source_path.name.lower().endswith(".md")
                and not destination_path.name.lower().endswith(".md")
            ):
                raise ValueError("A Markdown note must keep its .md extension")
            if snapshots is None:
                if rewrites != []:
                    raise ValueError("Note rewrites require a complete scan")
            else:
                self.validate_link_plan(workspace_id, snapshots, rewrites)

            moved_rewrites = [
                (path_after_move(note["path"], source, destination), note)
                for note in rewrites
            ]
            moved_active_note = None
            if self._active_note is not None:
                active = Path(self._active_note).relative_to(tree.root).as_posix()
                moved_active = path_after_move(active, source, destination)
                if moved_active != active:
                    moved_active_note = tree.root / moved_active
            moved_open_files: list[Path] = []
            rebased_open_files: set[str] = set()
            for watched in self._open_notes:
                try:
                    watched_rel = Path(watched).relative_to(tree.root).as_posix()
                except ValueError:
                    rebased_open_files.add(watched)
                    continue
                moved_rel = path_after_move(watched_rel, source, destination)
                if moved_rel != watched_rel:
                    moved_path = tree.root / moved_rel
                    rebased_open_files.add(os.path.normcase(os.path.abspath(moved_path)))
                    moved_open_files.append(moved_path)
                else:
                    rebased_open_files.add(watched)

            # The bridge lock serializes app operations. External writers can still
            # change files between checks, the rename, and individual note saves.
            tree.move_entry(source, destination)
            if moved_active_note is not None:
                self._active_note = os.path.normcase(os.path.abspath(moved_active_note))
            if self._open_notes_registered:
                self._open_notes = rebased_open_files

            result: MoveResult = {
                "destination": destination,
                "updated": [],
                "failures": [],
            }
            for path, note in moved_rewrites:
                try:
                    if note_path(tree.root, path) != tree.root / path:
                        raise NoteConflictError(
                            "Note path changed to a link or junction"
                        )
                    save_note(
                        tree.root,
                        path,
                        note["content"],
                        note["version"],
                        note.get("has_bom", False),
                    )
                except (OSError, NoteConflictError, ValueError) as error:
                    result["failures"].append({"path": path, "error": str(error)})
                else:
                    result["updated"].append(path)
            if moved_active_note is not None:
                self._note_changed(moved_active_note)
            for moved_path in moved_open_files:
                self._note_changed(moved_path)
            return result

    def resolve_note_link(
        self, workspace_id: str, note: str, href: str
    ) -> dict[str, str]:
        """Resolve a Markdown note link without opening it or discarding edits."""
        with self._lock:
            root = self._require_tree(workspace_id).root
            path, fragment = resolve_note_link(root, note, href)
            return {"path": path, "fragment": fragment}

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
        """Remember the active note for compatibility with older frontends."""
        with self._lock:
            root = self._require_tree(workspace_id).root
            self._active_note = os.path.normcase(
                os.path.abspath(note_path(root, path))
            )

    def set_open_files(self, workspace_id: str, paths: list[str]) -> None:
        """Replace the set of open workspace tabs watched for external changes."""
        if not isinstance(paths, list) or any(
            not isinstance(path, str) for path in paths
        ):
            raise ValueError("Expected a list of workspace-relative file paths")
        with self._lock:
            root = self._require_tree(workspace_id).root
            open_files = {
                os.path.normcase(os.path.abspath(workspace_file_path(root, path)))
                for path in paths
            }
            self._open_notes = open_files
            self._open_notes_registered = True
            if self._active_note not in open_files:
                self._active_note = None

    def set_open_notes(self, workspace_id: str, paths: list[str]) -> None:
        """Compatibility alias for replacing the set of watched open tabs."""
        self.set_open_files(workspace_id, paths)

    def save_note(
        self,
        workspace_id: str,
        path: str,
        content: str,
        version: str,
        has_bom: bool = False,
    ) -> NoteSnapshot:
        with self._lock:
            return save_note(
                self._require_tree(workspace_id).root,
                path,
                content,
                version,
                has_bom,
            )

    def save_text_file(
        self,
        workspace_id: str,
        path: str,
        content: str,
        version: str,
        has_bom: bool = False,
    ) -> TextFileSnapshot:
        with self._lock:
            return save_text_file(
                self._require_tree(workspace_id).root,
                path,
                content,
                version,
                has_bom,
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
            self._open_notes = set()
            self._open_notes_registered = False
            self._active_note = None
            tree.close()

    def _close(self) -> None:
        with self._lock:
            tree = self._tree
            self._tree = None
            self._open_notes = set()
            self._open_notes_registered = False
            self._active_note = None
            if tree is not None:
                tree.close()
        self._stopped = True
        self._signal_event.set()
        self._notifier.join(timeout=3)
