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
from backend.modules.notes import (
    NoteConflictError,
    NoteVersion,
    list_markdown_notes,
    read_note,
    read_note_batch,
    resolve_note_link,
    validate_note_rewrites,
    validate_note_scan,
)


class LinkPathTests(unittest.TestCase):
    def test_escaped_entity_and_leading_space_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertEqual(
                resolve_moved_targets(root, "note.md", "a&b.md", "new.md", [r"a\&amp;b.md"]),
                ["new.md"],
            )
            self.assertEqual(
                resolve_moved_targets(root, "note.md", " old.md", "new.md", ["< old.md>"]),
                ["<new.md>"],
            )
            self.assertEqual(
                resolve_moved_targets(root, "note.md", "other.md", "new.md", ["< old.md>"]),
                [None],
            )

    def test_reentered_folder_link_resolves_after_rename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "docs").mkdir()
            (root / "docs/note.md").touch()
            (root / "docs/target.md").touch()
            targets = [
                "../docs/target.md#part",
                "%2e%2e/docs/target.md",
                "./target.md#part",
            ]
            changes = resolve_moved_targets(
                root, "docs/note.md", "docs", "notes", targets
            )
            self.assertEqual(changes, ["target.md#part", "target.md", None])
            (root / "docs").rename(root / "notes")
            for original, replacement in zip(targets, changes, strict=True):
                actual, _ = resolve_note_link(
                    root, "notes/note.md", replacement or original
                )
                self.assertTrue((root / actual).samefile(root / "notes/target.md"))

    def test_numeric_entities_in_path_preserve_fragment_and_unrelated_links(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            targets = [
                "file&#32;name.md",
                "file&#x20;name&#46;md#part&#32;2",
                "<file&#32;name.md#>",
            ]
            self.assertEqual(
                resolve_moved_targets(
                    root, "note.md", "unrelated.md", "other.md", targets
                ),
                [None, None, None],
            )
            self.assertEqual(
                resolve_moved_targets(
                    root, "note.md", "file name.md", "new name.md", targets
                ),
                ["new%20name.md", "new%20name.md#part&#32;2", "<new name.md#>"],
            )

    def test_plan_validation_detects_changed_unmodified_and_added_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "a.md").write_text("a", encoding="utf-8")
            (root / "b.md").write_text("b", encoding="utf-8")
            first = read_note(root, "a.md")
            second = read_note(root, "b.md")
            snapshots: list[NoteVersion] = [
                {"path": n["path"], "version": n["version"]} for n in (first, second)
            ]
            versions = validate_note_scan(root, snapshots)
            validate_note_rewrites(root, [first], versions)
            with self.assertRaises(ValueError):
                validate_note_rewrites(root, [{**first, "version": "wrong"}], versions)
            (root / "b.md").write_text("changed", encoding="utf-8")
            with self.assertRaises(NoteConflictError):
                validate_note_scan(root, snapshots)
            (root / "b.md").write_text("b", encoding="utf-8")
            (root / "new.md").write_text("new", encoding="utf-8")
            with self.assertRaises(NoteConflictError):
                validate_note_scan(root, snapshots)
            with self.assertRaises(ValueError):
                validate_note_rewrites(root, [first, first])

    def test_invalid_entities_and_utf8_in_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = parse_markdown_target(root, "note.md", "a&copycat;z.md")
            assert target is not None
            self.assertEqual(target.path, "a&copycat;z.md")
            with self.assertRaises(ValueError):
                parse_markdown_target(root, "note.md", "%FF.md")

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

    def test_queries_block_only_links_whose_paths_need_rewriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertEqual(
                resolve_moved_targets(
                    root,
                    "docs/note.md",
                    "docs",
                    "archive/docs",
                    ["image.png?version=2", "?self=1", "https://example.com?test=1"],
                ),
                [None, None, None],
            )
            for target in ("file.md?", "file.md?version=2#heading", "file.md&#63;q=1"):
                with self.subTest(target=target), self.assertRaisesRegex(
                    ValueError, "link with a query"
                ):
                    resolve_moved_targets(
                        root, "note.md", "file.md", "archive/file.md", [target]
                    )
            self.assertEqual(
                resolve_moved_targets(
                    root, "note.md", "file.md", "archive/file.md", ["file.md#h?q"]
                ),
                ["archive/file.md#h?q"],
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
