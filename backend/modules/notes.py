"""Coordinate note workflows, including Markdown and note-link behavior."""

import hashlib
import os
import stat
import tempfile
from pathlib import Path
from typing import TypedDict


class NoteSnapshot(TypedDict):
    path: str
    content: str
    version: str


class NoteConflictError(Exception):
    """Signal that the file no longer matches the version being edited."""


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
