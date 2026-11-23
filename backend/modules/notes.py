"""Coordinate note workflows, including Markdown and note-link behavior."""

import hashlib
import os
import stat
import tempfile
from pathlib import Path
from typing import TypedDict
from urllib.parse import unquote, urlsplit


class NoteSnapshot(TypedDict):
    path: str
    content: str
    version: str


class NoteBatch(TypedDict):
    notes: list[NoteSnapshot]
    next_index: int


def list_markdown_notes(root: Path) -> list[str]:
    """List workspace Markdown files without following links or hiding scan errors."""
    def raise_scan_error(error: OSError) -> None:
        raise error

    paths: list[str] = []
    for folder, directories, files in os.walk(root, onerror=raise_scan_error):
        parent = Path(folder)
        # Linked directories and files need a deliberate policy before planning moves.
        for name in directories + files:
            path = parent / name
            if path.is_symlink() or path.is_junction():
                raise ValueError(f"Cannot plan across a link or junction: {path}")
        for name in files:
            if Path(name).suffix.lower() == ".md":
                paths.append((parent / name).relative_to(root).as_posix())
    return sorted(paths)


def read_note_batch(
    root: Path, paths: list[str], start: int, max_bytes: int, max_notes: int
) -> NoteBatch:
    """Read a bounded batch; a single oversized note is returned on its own."""
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise TypeError("Note paths must be a list of strings")
    if any(type(value) is not int for value in (start, max_bytes, max_notes)):
        raise TypeError("Batch limits must be integers")
    if (
        not 0 <= start <= len(paths)
        or not 1 <= max_bytes <= 2_000_000
        or not 1 <= max_notes <= 100
    ):
        raise ValueError("Invalid note batch limits")
    notes: list[NoteSnapshot] = []
    total = 0
    index = start
    while index < len(paths) and len(notes) < max_notes:
        note = read_note(root, paths[index])
        size = len(note["content"].encode("utf-8"))
        if notes and total + size > max_bytes:
            break
        notes.append(note)
        total += size
        index += 1
    return {"notes": notes, "next_index": index}


class NoteConflictError(Exception):
    """Signal that the file no longer matches the version being edited."""


def markdown_name(name: str) -> str:
    """Add the Markdown extension when the supplied name does not have it."""
    if not isinstance(name, str) or not name.strip() or name.endswith((" ", ".")):
        raise ValueError("A note name is required")
    return name if name.lower().endswith(".md") else f"{name}.md"


def resolve_note_link(root: Path, note: str, href: str) -> tuple[str, str]:
    """Resolve a relative link inside the workspace against its note."""
    if not isinstance(href, str) or not href:
        raise ValueError("Link must be a non-empty string")
    parts = urlsplit(href)
    if parts.scheme or parts.netloc or parts.query:
        raise ValueError("Expected a relative local link")
    decoded = unquote(parts.path)
    if "\\" in decoded or "\x00" in decoded or Path(decoded).anchor:
        raise ValueError("Invalid local link")
    source = note_path(root, note)
    target = (source.parent / decoded).resolve() if decoded else source
    try:
        relative = target.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError("Link must stay inside the workspace") from error
    return relative.as_posix(), unquote(parts.fragment)


def note_path(root: Path, relative: str) -> Path:
    """Resolve a Markdown file inside the active workspace."""
    if not isinstance(relative, str) or not relative:
        raise ValueError("Note path must be a non-empty string")
    path = Path(relative)
    if path.anchor or ".." in path.parts or path.suffix.lower() != ".md":
        raise ValueError("Note must be a workspace-relative Markdown file")
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("Note must stay inside the workspace") from error
    return resolved


def read_note(root: Path, relative: str) -> NoteSnapshot:
    """Read UTF-8 bytes and identify the exact disk version by its hash."""
    data = note_path(root, relative).read_bytes()
    return {
        "path": relative,
        "content": data.decode("utf-8"),
        "version": hashlib.sha256(data).hexdigest(),
    }


def save_note(
    root: Path, relative: str, content: str, expected_version: str
) -> NoteSnapshot:
    """Replace an unchanged note with UTF-8 content using a nearby temporary file."""
    if not isinstance(content, str) or not isinstance(expected_version, str):
        raise TypeError("Content and expected version must be strings")
    path = note_path(root, relative)
    data = content.encode("utf-8")
    temporary: str | None = None
    try:
        # A failed temporary write cannot truncate the existing note.
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".acornwiki-", delete=False
        ) as file:
            temporary = file.name
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        try:
            current = path.read_bytes()
            mode = stat.S_IMODE(path.stat().st_mode)
        except FileNotFoundError as error:
            raise NoteConflictError("Note was deleted or moved") from error
        if hashlib.sha256(current).hexdigest() != expected_version:
            raise NoteConflictError("Note changed on disk")
        os.chmod(temporary, mode)
        # Another process can still write between the version check and replacement.
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)
    return {
        "path": relative,
        "content": content,
        "version": hashlib.sha256(data).hexdigest(),
    }
