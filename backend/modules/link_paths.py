"""Calculate workspace-relative link paths after a file or folder move."""

import html
import html.entities
import ntpath
import os
import posixpath
import re
import string
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from backend.modules.notes import resolve_note_link


@dataclass(frozen=True)
class MarkdownTarget:
    """Keep the resolved target and the original syntax needed for rewriting."""

    path: str
    relative_path: str
    angled: bool
    encoded_unicode: bool
    fragment: str
    has_query: bool


_DESTINATION_TOKEN = re.compile(
    r"\\(["
    + re.escape(string.punctuation)
    + r"])|(&#(?:[xX][0-9a-fA-F]+|[0-9]+);|&[a-zA-Z][a-zA-Z0-9]+;)|#"
)


def _decode_before_fragment(value: str) -> tuple[str, str]:
    """Decode the URL prefix while preserving the source spelling of the fragment."""
    chunks: list[str] = []
    start = 0
    for match in _DESTINATION_TOKEN.finditer(value):
        chunks.append(value[start : match.start()])
        token = match[0]
        if token == "#":
            return "".join(chunks), value[match.start() :]
        if match.group(1) is not None:
            chunks.append(match[1])
        elif token.startswith("&#") or token[1:] in html.entities.html5:
            chunks.append(html.unescape(token))
        else:
            chunks.append(token)
        start = match.end()
    chunks.append(value[start:])
    return "".join(chunks), ""


def parse_markdown_target(
    root: Path, note: str, raw_target: str
) -> MarkdownTarget | None:
    """Resolve a local destination and keep the original fragment."""
    if not isinstance(raw_target, str) or not raw_target:
        raise ValueError("A Markdown target is required")
    angled = raw_target.startswith("<") and raw_target.endswith(">")
    inner = raw_target[1:-1] if angled else raw_target
    decoded, fragment = _decode_before_fragment(inner)
    parts = urlsplit(decoded)
    if parts.scheme or parts.netloc or not parts.path:
        return None
    has_query = "?" in decoded.split("#", 1)[0]
    # Reject fragment delimiters that cannot be split from the raw text safely.
    if not has_query and decoded != parts.path:
        raise ValueError("Cannot preserve this Markdown fragment safely")
    try:
        relative_path = unquote(parts.path, errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("Link path has invalid UTF-8 encoding") from error
    path, _ = resolve_note_link(root, note, parts.path)
    encoded_unicode = bool(re.search(r"%(?:[c-fC-F][0-9a-fA-F])", parts.path))
    return MarkdownTarget(
        path, relative_path, angled, encoded_unicode, fragment, has_query
    )


def format_markdown_target(target: MarkdownTarget, relative_path: str) -> str:
    """Format a new path and preserve the relevant original syntax."""
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        raise ValueError("Expected a relative URL path")
    if target.has_query:
        raise ValueError("Cannot safely rewrite a local Markdown link with a query")
    encoded = []
    for char in relative_path:
        if (
            ord(char) > 127
            and not target.encoded_unicode
            and not unicodedata.category(char).startswith("C")
        ):
            encoded.append(char)
        elif char in "/-._~" or char.isascii() and char.isalnum():
            encoded.append(char)
        elif target.angled and char in " ()":
            encoded.append(char)
        elif not target.angled and char in "()":
            encoded.append("\\" + char)
        else:
            encoded.append(quote(char, safe=""))
    value = "".join(encoded) + target.fragment
    return f"<{value}>" if target.angled else value


def _parts(path: str, *, allow_root: bool = False) -> list[str]:
    """Accept canonical workspace-relative POSIX paths, not filesystem paths."""
    if (
        not isinstance(path, str)
        or not path
        or "\\" in path
        or "\x00" in path
        or ntpath.splitdrive(path)[0]
    ):
        raise ValueError("Expected a workspace-relative path")
    if path == "." and allow_root:
        return []
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("Expected a canonical workspace-relative path")
    return parts


def path_after_move(path: str, source: str, destination: str) -> str:
    """Map a path inside a moved entry to its new location; leave other paths alone."""
    parts = _parts(path, allow_root=True)
    source_parts = _parts(source)
    destination_parts = _parts(destination)

    # Windows paths compare without case, while output keeps the supplied spelling.
    prefix = parts[: len(source_parts)]
    if len(prefix) == len(source_parts) and all(
        os.path.normcase(left) == os.path.normcase(right)
        for left, right in zip(prefix, source_parts, strict=True)
    ):
        return "/".join(destination_parts + parts[len(source_parts) :])
    return path


def link_path_after_move(
    note: str,
    target: str,
    source: str,
    destination: str,
    *,
    original_relative: str | None = None,
) -> str | None:
    """Return a new relative path, or None when the old path remains valid."""
    _parts(note)
    _parts(target, allow_root=True)
    moved_note = path_after_move(note, source, destination)
    moved_target = path_after_move(target, source, destination)
    old_parent = posixpath.dirname(note)
    new_parent = posixpath.dirname(moved_note)
    old_relative = posixpath.relpath(target, old_parent or ".")
    new_relative = posixpath.relpath(moved_target, new_parent or ".")
    if old_relative != new_relative:
        return new_relative
    if original_relative is not None and old_parent != new_parent:
        # An internal link may leave the folder and re-enter it by its former name.
        retained_target = posixpath.normpath(
            posixpath.join(new_parent, original_relative)
        )
        if os.path.normcase(retained_target) != os.path.normcase(moved_target):
            return new_relative
    return None


def resolve_moved_targets(
    root: Path, note: str, source: str, destination: str, raw_targets: list[str]
) -> list[str | None]:
    """Plan new Markdown destinations without moving or writing files."""
    _parts(note)
    _parts(source)
    _parts(destination)
    if not isinstance(raw_targets, list):
        raise TypeError("Markdown targets must be a list")
    results: list[str | None] = []
    for raw in raw_targets:
        target = parse_markdown_target(root, note, raw)
        if target is None:
            results.append(None)
            continue
        new_path = link_path_after_move(
            note,
            target.path,
            source,
            destination,
            original_relative=target.relative_path,
        )
        if new_path is not None and target.has_query:
            raise ValueError(f"Cannot rewrite a local link with a query in {note}")
        results.append(
            None if new_path is None else format_markdown_target(target, new_path)
        )
    return results
