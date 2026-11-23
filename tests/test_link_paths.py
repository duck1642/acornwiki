"""Check relative link calculations independently of Markdown parsing and file I/O."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.modules.link_paths import (
    format_markdown_target,
    link_path_after_move,
    parse_markdown_target,
    path_after_move,
    resolve_moved_targets,
)
from backend.modules.notes import list_markdown_notes, read_note_batch


class LinkPathTests(unittest.TestCase):
    def test_note_batches_preserve_versions_and_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "folder").mkdir()
            (root / "a.md").write_bytes(b"a\r\n")
            (root / "folder" / "b.MD").write_bytes(b"123456")
            (root / "ignored.txt").write_text("ignored")
            paths = list_markdown_notes(root)
            self.assertEqual(paths, ["a.md", "folder/b.MD"])
            batch = read_note_batch(root, paths, 0, 4, 50)
            self.assertEqual([n["path"] for n in batch["notes"]], ["a.md"])
            self.assertEqual(batch["notes"][0]["content"], "a\r\n")
            self.assertEqual(len(batch["notes"][0]["version"]), 64)
            batch = read_note_batch(root, paths, batch["next_index"], 4, 50)
            self.assertEqual(batch["notes"][0]["path"], "folder/b.MD")
            self.assertEqual(batch["next_index"], 2)
            with self.assertRaises(ValueError):
                read_note_batch(root, paths, 0, 2_000_001, 50)
            with self.assertRaises(ValueError):
                read_note_batch(root, ["../outside.md"], 0, 100, 1)

    def test_plan_target_replacements_without_writing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "docs").mkdir()
            note = root / "docs" / "note.md"
            note.write_bytes(b"unchanged\r\n")
            targets = [
                "file.md#heading",
                "../other.md",
                "https://example.com",
                "#heading",
            ]
            self.assertEqual(
                resolve_moved_targets(
                    root, "docs/note.md", "docs", "archive/docs", targets
                ),
                [None, "../../other.md", None, None],
            )
            self.assertEqual(note.read_bytes(), b"unchanged\r\n")
            self.assertEqual(
                resolve_moved_targets(
                    root, "docs/note.md", "docs/file.md", "archive/file.md", targets
                ),
                ["../archive/file.md#heading", None, None, None],
            )
            with self.assertRaises(ValueError):
                resolve_moved_targets(
                    root, "docs/note.md", "docs", "archive/docs", ["../../outside.md"]
                )

    def test_markdown_targets_preserve_unicode_and_style(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "notlar").mkdir()
            cases = [
                (
                    "<özet dosya.md#b%C3%B6l%C3%BCm>",
                    "notlar/özet dosya.md",
                    "<../arsiv/özet dosya.md#b%C3%B6l%C3%BCm>",
                ),
                ("özet.md", "notlar/özet.md", "../arsiv/özet dosya.md"),
                ("%C3%B6zet.md", "notlar/özet.md", "../arsiv/%C3%B6zet%20dosya.md"),
                (r"a\(b\).md", "notlar/a(b).md", r"../arsiv/a\(b\).md"),
            ]
            for raw, path, expected in cases:
                with self.subTest(raw=raw):
                    target = parse_markdown_target(root, "notlar/note.md", raw)
                    self.assertIsNotNone(target)
                    assert target is not None
                    self.assertEqual(target.path, path)
                    new = (
                        "../arsiv/a(b).md"
                        if raw.startswith("a")
                        else "../arsiv/özet dosya.md"
                    )
                    if raw == "özet.md":
                        expected = "../arsiv/özet%20dosya.md"
                    self.assertEqual(format_markdown_target(target, new), expected)

    def test_markdown_target_filters_and_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for raw in (
                "https://example.com/a",
                "#heading",
                "file.md?query=1",
                "&#104;ttp://example.com",
            ):
                with self.subTest(raw=raw):
                    self.assertIsNone(parse_markdown_target(root, "note.md", raw))
            with self.assertRaises(ValueError):
                parse_markdown_target(root, "note.md", "%2e%2e/outside.md")
            with self.assertRaises(ValueError):
                parse_markdown_target(root, "note.md", "file.md&#35;section")
            target = parse_markdown_target(
                root, "note.md", "a&amp;b.md#b%C3%B6l%C3%BCm"
            )
            assert target is not None
            self.assertEqual(target.path, "a&b.md")
            self.assertEqual(
                format_markdown_target(target, "yeni & eski.md"),
                "yeni%20%26%20eski.md#b%C3%B6l%C3%BCm",
            )

    def test_target_and_note_moves(self) -> None:
        self.assertEqual(
            link_path_after_move(
                "notlar/gunluk.md", "rehber.md", "rehber.md", "arsiv/rehber.md"
            ),
            "../arsiv/rehber.md",
        )
        self.assertEqual(
            link_path_after_move(
                "notlar/gunluk.md", "rehber.md", "notlar/gunluk.md", "arsiv/gunluk.md"
            ),
            None,
        )
        self.assertEqual(
            link_path_after_move(
                "notlar/gunluk.md",
                "rehber.md",
                "notlar/gunluk.md",
                "arsiv/eski/gunluk.md",
            ),
            "../../rehber.md",
        )

    def test_folder_move_preserves_internal_links(self) -> None:
        self.assertIsNone(
            link_path_after_move(
                "docs/note.md", "docs/img/a.png", "docs", "archive/docs"
            )
        )
        self.assertEqual(
            link_path_after_move(
                "other/note.md", "docs/img/a.png", "docs", "archive/docs"
            ),
            "../archive/docs/img/a.png",
        )
        self.assertEqual(
            link_path_after_move("docs/note.md", "other/a.png", "docs", "archive/docs"),
            "../../other/a.png",
        )

    def test_prefixes_are_path_segments_and_case_changes_are_preserved(self) -> None:
        self.assertEqual(
            path_after_move("docs2/file.md", "docs", "new"), "docs2/file.md"
        )
        self.assertEqual(
            path_after_move("docs/file.md", "docs", "Docs"), "Docs/file.md"
        )
        self.assertEqual(
            link_path_after_move("note.md", "docs/file.md", "docs", "Docs"),
            "Docs/file.md",
        )

    def test_windows_case_insensitive_comparison(self) -> None:
        with patch(
            "backend.modules.link_paths.os.path.normcase", side_effect=str.lower
        ):
            self.assertEqual(
                path_after_move("DOCS/file.md", "docs", "archive"), "archive/file.md"
            )

    def test_reject_noncanonical_paths(self) -> None:
        for invalid in (
            "",
            "../a",
            "/a",
            "a/../b",
            "a//b",
            "a\\b",
            "a/",
            "a/./b",
            "C:/a",
        ):
            with self.subTest(path=invalid), self.assertRaises(ValueError):
                path_after_move(invalid, "source", "destination")
        with self.assertRaises(ValueError):
            path_after_move("file.md", ".", "destination")


if __name__ == "__main__":
    unittest.main()
