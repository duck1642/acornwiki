"""Coordinate workspace Markdown note and UTF-8 text file I/O."""

import hashlib
import ntpath
import os
import stat
import tempfile
from pathlib import Path
from typing import Literal, NotRequired, TypedDict
from urllib.parse import unquote, urlsplit

UTF8_BOM = b"\xef\xbb\xbf"
UTF16_UTF32_BOMS = (
    b"\xff\xfe\x00\x00",
    b"\x00\x00\xfe\xff",
    b"\xff\xfe",
    b"\xfe\xff",
)
TEXT_FILE_MAX_BYTES = 2 * 1024 * 1024


class NoteSnapshot(TypedDict):
    path: str
    content: str
    version: str
    has_bom: NotRequired[bool]


class TextFileSnapshot(TypedDict):
    path: str
    content: str
    version: str
    has_bom: bool


class TextFileReadSuccess(TextFileSnapshot):
    ok: Literal[True]
    size_bytes: int


class TextFileReadFailure(TypedDict):
    ok: Literal[False]
    path: str
    reason: Literal["too_large", "binary", "unsupported_encoding"]
    size_bytes: int
    max_bytes: int


type TextFileReadResult = TextFileReadSuccess | TextFileReadFailure


class NoteBatch(TypedDict):
    notes: list[NoteSnapshot]
    next_index: int


class NoteVersion(TypedDict):
    path: str
    version: str


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
            if name.lower().endswith(".md"):
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


def validate_note_rewrites(
    root: Path, rewrites: list[NoteSnapshot], versions: dict[str, str] | None = None
) -> None:
    """Check planned note versions before starting a multi-file operation."""
    if not isinstance(rewrites, list):
        raise TypeError("Note rewrites must be a list")
    seen: set[str] = set()
    for rewrite in rewrites:
        if not isinstance(rewrite, dict) or not all(
            isinstance(rewrite.get(key), str) for key in ("path", "content", "version")
        ):
            raise ValueError("Invalid note rewrite")
        if "has_bom" in rewrite and not isinstance(rewrite["has_bom"], bool):
            raise ValueError("Invalid note rewrite")
        # Reject content that cannot be written before starting the move.
        rewrite["content"].encode("utf-8")
        path = note_path(root, rewrite["path"])
        key = os.path.normcase(str(path))
        if key in seen:
            raise ValueError("A note cannot appear twice in the plan")
        seen.add(key)
        if versions is not None:
            if versions.get(rewrite["path"]) != rewrite["version"]:
                raise ValueError("Rewrites must belong to the scanned note versions")
            continue
        try:
            current = path.read_bytes()
        except FileNotFoundError as error:
            raise NoteConflictError(
                f"Note was deleted or moved: {rewrite['path']}"
            ) from error
        if hashlib.sha256(current).hexdigest() != rewrite["version"]:
            raise NoteConflictError(f"Note changed on disk: {rewrite['path']}")


def validate_note_scan(root: Path, snapshots: list[NoteVersion]) -> dict[str, str]:
    """Reject a plan if any scanned note changed or the set of notes differs."""
    if not isinstance(snapshots, list):
        raise TypeError("Note versions must be a list")
    seen: set[str] = set()
    for snapshot in snapshots:
        if not isinstance(snapshot, dict) or not all(
            isinstance(snapshot.get(key), str) for key in ("path", "version")
        ):
            raise ValueError("Invalid note version")
        path = note_path(root, snapshot["path"])
        key = os.path.normcase(str(path))
        if key in seen:
            raise ValueError("A note cannot appear twice in the scan")
        seen.add(key)
        try:
            current = path.read_bytes()
        except FileNotFoundError as error:
            raise NoteConflictError(
                f"Note was deleted or moved: {snapshot['path']}"
            ) from error
        if hashlib.sha256(current).hexdigest() != snapshot["version"]:
            raise NoteConflictError(f"Note changed on disk: {snapshot['path']}")
    current_paths = {
        os.path.normcase(str(note_path(root, path)))
        for path in list_markdown_notes(root)
    }
    if seen != current_paths:
        raise NoteConflictError("The workspace note list changed")
    return {snapshot["path"]: snapshot["version"] for snapshot in snapshots}


def markdown_name(name: str) -> str:
    """Add the Markdown extension when the supplied name does not have it."""
    if (
        not isinstance(name, str)
        or not name.strip()
        or name.endswith((" ", "."))
    ):
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


def workspace_file_path(root: Path, relative: str) -> Path:
    """Resolve a workspace-relative file path inside the active workspace."""
    if not isinstance(relative, str) or not relative:
        raise ValueError("File path must be a non-empty string")
    if "\x00" in relative or ":" in relative:
        raise ValueError("Invalid workspace file path")
    path = Path(relative)
    if path.anchor or not path.parts or ".." in path.parts:
        raise ValueError("File must be a workspace-relative path")
    if any(ntpath.isreserved(part) for part in path.parts):
        raise ValueError("Reserved file name is not allowed")
    resolved_root = root.resolve()
    resolved = (resolved_root / path).resolve()
    if resolved == resolved_root:
        raise ValueError("File path cannot refer to the workspace root")
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("File must stay inside the workspace") from error
    return resolved


def note_path(root: Path, relative: str) -> Path:
    """Resolve a Markdown file inside the active workspace."""
    resolved = workspace_file_path(root, relative)
    if not Path(relative).name.lower().endswith(".md"):
        raise ValueError("Note must be a workspace-relative Markdown file")
    return resolved


def _decode_utf8_with_bom(data: bytes) -> tuple[str, bool]:
    has_bom = data.startswith(UTF8_BOM)
    body = data[len(UTF8_BOM):] if has_bom else data
    return body.decode("utf-8"), has_bom


def _encode_utf8_with_bom(content: str, has_bom: bool) -> bytes:
    return (UTF8_BOM if has_bom else b"") + content.encode("utf-8")


def _file_version_and_mode(path: Path, label: str = "File") -> tuple[str, int]:
    """Hash an existing regular file in bounded memory and return its digest and mode."""
    try:
        info = path.stat()
    except FileNotFoundError as error:
        raise NoteConflictError(f"{label} was deleted or moved") from error
    if stat.S_ISDIR(info.st_mode):
        raise IsADirectoryError(f"Expected a file, got a directory: {path.name}")
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Expected a regular file: {path.name}")
    try:
        with path.open("rb") as existing:
            fd_info = os.fstat(existing.fileno())
            if not stat.S_ISREG(fd_info.st_mode):
                raise ValueError(f"Expected a regular file: {path.name}")
            digest = hashlib.file_digest(existing, "sha256").hexdigest()
            return digest, stat.S_IMODE(fd_info.st_mode)
    except FileNotFoundError as error:
        raise NoteConflictError(f"{label} was deleted or moved") from error


def _save_workspace_bytes(
    path: Path, data: bytes, expected_version: str, label: str = "File"
) -> str:
    """Replace an unchanged workspace file atomically using a nearby temporary file."""
    current_version, _ = _file_version_and_mode(path, label)
    if current_version != expected_version:
        raise NoteConflictError(f"{label} changed on disk")
    temporary: str | None = None
    try:
        # A failed temporary write cannot truncate the existing file.
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".acornwiki-", delete=False
            ) as file:
                temporary = file.name
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
        except FileNotFoundError as error:
            raise NoteConflictError(f"{label} was deleted or moved") from error
        current_version, mode = _file_version_and_mode(path, label)
        if current_version != expected_version:
            raise NoteConflictError(f"{label} changed on disk")
        os.chmod(temporary, mode)
        # Another process can still write between the version check and replacement.
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            # Make read-only temporary files writable before unlinking on Windows.
            try:
                os.chmod(temporary, stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass
            try:
                os.unlink(temporary)
            except OSError:
                pass
    return hashlib.sha256(data).hexdigest()


def read_note(root: Path, relative: str) -> NoteSnapshot:
    """Read UTF-8 bytes and identify the exact disk version by its hash."""
    data = note_path(root, relative).read_bytes()
    content, has_bom = _decode_utf8_with_bom(data)
    return {
        "path": relative,
        "content": content,
        "version": hashlib.sha256(data).hexdigest(),
        "has_bom": has_bom,
    }


def save_note(
    root: Path,
    relative: str,
    content: str,
    expected_version: str,
    has_bom: bool = False,
) -> NoteSnapshot:
    """Replace an unchanged note with UTF-8 content (with BOM when has_bom is True)."""
    if (
        not isinstance(content, str)
        or not isinstance(expected_version, str)
        or not isinstance(has_bom, bool)
    ):
        raise TypeError("Content, expected version, and BOM flag must have valid types")
    path = note_path(root, relative)
    data = _encode_utf8_with_bom(content, has_bom)
    version = _save_workspace_bytes(path, data, expected_version, label="Note")
    return {
        "path": relative,
        "content": content,
        "version": version,
        "has_bom": has_bom,
    }


def read_text_file(
    root: Path, relative: str, max_bytes: int = TEXT_FILE_MAX_BYTES
) -> TextFileReadResult:
    """Read a bounded UTF-8 text file or report why it cannot be edited."""
    if type(max_bytes) is not int:
        raise TypeError("max_bytes must be an integer")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    path = workspace_file_path(root, relative)
    pre_info = path.stat()
    if stat.S_ISDIR(pre_info.st_mode):
        raise IsADirectoryError(f"Expected a file, got a directory: {relative}")
    if not stat.S_ISREG(pre_info.st_mode):
        raise ValueError(f"Expected a regular file: {relative}")
    if pre_info.st_size > max_bytes:
        return {
            "ok": False,
            "path": relative,
            "reason": "too_large",
            "size_bytes": pre_info.st_size,
            "max_bytes": max_bytes,
        }
    with path.open("rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"Expected a regular file: {relative}")
        if info.st_size > max_bytes:
            return {
                "ok": False,
                "path": relative,
                "reason": "too_large",
                "size_bytes": info.st_size,
                "max_bytes": max_bytes,
            }
        data = file.read(max_bytes + 1)
    if len(data) > max_bytes:
        return {
            "ok": False,
            "path": relative,
            "reason": "too_large",
            "size_bytes": len(data),
            "max_bytes": max_bytes,
        }
    if data.startswith(UTF16_UTF32_BOMS):
        return {
            "ok": False,
            "path": relative,
            "reason": "unsupported_encoding",
            "size_bytes": len(data),
            "max_bytes": max_bytes,
        }
    if b"\x00" in data:
        return {
            "ok": False,
            "path": relative,
            "reason": "binary",
            "size_bytes": len(data),
            "max_bytes": max_bytes,
        }
    try:
        content, has_bom = _decode_utf8_with_bom(data)
    except UnicodeDecodeError:
        return {
            "ok": False,
            "path": relative,
            "reason": "unsupported_encoding",
            "size_bytes": len(data),
            "max_bytes": max_bytes,
        }
    return {
        "ok": True,
        "path": relative,
        "content": content,
        "version": hashlib.sha256(data).hexdigest(),
        "has_bom": has_bom,
        "size_bytes": len(data),
    }


def save_text_file(
    root: Path,
    relative: str,
    content: str,
    expected_version: str,
    has_bom: bool = False,
) -> TextFileSnapshot:
    """Replace an unchanged workspace text file atomically (writing BOM if has_bom)."""
    if (
        not isinstance(content, str)
        or not isinstance(expected_version, str)
        or not isinstance(has_bom, bool)
    ):
        raise TypeError("Content, expected version, and BOM flag must have valid types")
    path = workspace_file_path(root, relative)
    data = _encode_utf8_with_bom(content, has_bom)
    if len(data) > TEXT_FILE_MAX_BYTES:
        raise ValueError(f"Text file exceeds the {TEXT_FILE_MAX_BYTES}-byte limit")
    if b"\x00" in data:
        raise ValueError("Text files cannot contain NUL bytes")
    version = _save_workspace_bytes(path, data, expected_version)
    return {
        "path": relative,
        "content": content,
        "version": version,
        "has_bom": has_bom,
    }
