"""Focused tests for file-tree caching, scheduling and Windows watcher events."""

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Callable
from unittest.mock import patch

from backend.app.bridge import Bridge
from backend.services.filesystem import (
    DirectorySnapshot,
    FileTree,
    FileTreeItem,
    scan_dir,
)


def wait_until(predicate: Callable[[], bool], timeout: float = 5) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for file-tree update")


def directory(tree: FileTree, path: str) -> DirectorySnapshot:
    return next(d for d in tree.snapshot()["directories"] if d["path"] == path)


class FileTreeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.tree = FileTree(self.root, lambda: None)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.tree.close)

    def test_lazy_load_cache_and_boundaries(self) -> None:
        (self.root / "nested").mkdir()
        (self.root / "nested" / "file.md").write_text("hello")
        self.tree.set_visible("", True)
        wait_until(lambda: directory(self.tree, "")["items"] is not None)
        self.assertEqual([d["path"] for d in self.tree.snapshot()["directories"]], [""])
        self.tree.set_visible("nested", True)
        wait_until(lambda: directory(self.tree, "nested")["items"] is not None)
        self.tree.set_visible("nested", False)
        items = directory(self.tree, "nested")["items"] or []
        self.assertEqual(items[0]["name"], "file.md")
        with self.assertRaises(ValueError):
            self.tree.set_visible("../outside", True)

    def test_create_note_and_folder_without_overwriting(self) -> None:
        bridge = Bridge()
        self.addCleanup(bridge._close)
        workspace = bridge.open_workspace(str(self.root))["workspace_id"]
        self.assertEqual(bridge.create_directory(workspace, "", "Notes"), "Notes")
        self.assertEqual(bridge.create_note(workspace, "Notes", "Günlük"), "Notes/Günlük.md")
        self.assertEqual(bridge.create_note(workspace, "Notes", "other.MD"), "Notes/other.MD")
        existing = self.root / "Notes" / "Günlük.md"
        existing.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            bridge.create_note(workspace, "Notes", "Günlük")
        with self.assertRaises(FileExistsError):
            bridge.create_directory(workspace, "", "Notes")
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep")
        with self.assertRaises(ValueError):
            bridge.create_note("old", "", "stale")

    def test_plan_link_targets_checks_workspace_without_changing_files(self) -> None:
        bridge = Bridge()
        self.addCleanup(bridge._close)
        workspace = bridge.open_workspace(str(self.root))["workspace_id"]
        note = self.root / "note.md"
        note.write_text("[link](old.md)", encoding="utf-8")
        self.assertEqual(
            bridge.plan_link_targets(workspace, "note.md", "old.md", "new.md", ["old.md"]),
            ["new.md"],
        )
        self.assertEqual(note.read_text(encoding="utf-8"), "[link](old.md)")
        paths = bridge.list_plan_notes(workspace)
        batch = bridge.read_plan_notes(workspace, paths, 0, 1000, 10)
        self.assertEqual(batch["notes"][0]["path"], "note.md")
        self.assertEqual(
            bridge.plan_link_targets_batch(workspace, "old.md", "new.md", [{"path": "note.md", "targets": ["old.md"]}]),
            [["new.md"]],
        )
        with self.assertRaises(ValueError):
            bridge.plan_link_targets("stale", "note.md", "old.md", "new.md", ["old.md"])
        with self.assertRaises(ValueError):
            bridge.read_plan_notes("stale", paths, 0, 1000, 10)

    def test_create_rejects_invalid_names_and_outside_directory(self) -> None:
        for name in ("", "..", " ", "CON", "bad/name", "bad\\name", "bad?.txt", "end."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.tree.create_entry("", name, False)
        with self.assertRaises(ValueError):
            self.tree.create_entry("../outside", "note.md", False)
        with self.assertRaises(FileNotFoundError):
            self.tree.create_entry("missing", "note.md", False)

    def test_created_entry_refreshes_visible_tree(self) -> None:
        self.tree.set_visible("", True)
        wait_until(lambda: directory(self.tree, "")["items"] == [])
        self.tree.create_entry("", "new.md", False)
        wait_until(lambda: any(i["name"] == "new.md" for i in (directory(self.tree, "")["items"] or [])))

    @unittest.skipUnless(os.name == "nt", "Windows rename semantics")
    def test_move_entry_preserves_existing_files_and_workspace_boundary(self) -> None:
        (self.root / "source").mkdir()
        (self.root / "target").mkdir()
        (self.root / "source" / "note.md").write_text("original", encoding="utf-8")
        (self.root / "target" / "note.md").write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.tree.move_entry("source/note.md", "target/note.md")
        self.assertEqual((self.root / "target" / "note.md").read_text(), "keep")
        with self.assertRaises(ValueError):
            self.tree.move_entry("source", "source/child")
        with self.assertRaises(ValueError):
            self.tree.move_entry("source", "../outside")
        with self.assertRaises(ValueError):
            self.tree.move_entry("", "target/root")
        self.assertEqual(self.tree.move_entry("source/note.md", "target/moved.md"), "target/moved.md")
        self.assertEqual((self.root / "target" / "moved.md").read_text(), "original")
        (self.root / "source" / "child").mkdir()
        (self.root / "source" / "child" / "inside.md").write_text("nested", encoding="utf-8")
        self.tree.move_entry("source", "target/source")
        self.assertEqual((self.root / "target" / "source" / "child" / "inside.md").read_text(), "nested")

    @unittest.skipUnless(os.name == "nt", "Windows rename semantics")
    def test_move_directory_case_and_remove_stale_cached_descendants(self) -> None:
        (self.root / "docs" / "nested").mkdir(parents=True)
        self.tree.set_visible("docs", True)
        self.tree.set_visible("docs/nested", True)
        wait_until(lambda: directory(self.tree, "docs/nested")["items"] is not None)
        self.assertEqual(self.tree.move_entry("docs", "Docs"), "Docs")
        self.assertEqual([p.name for p in self.root.iterdir()], ["Docs"])
        self.assertFalse(any(d["path"].lower().startswith("docs") for d in self.tree.snapshot()["directories"]))
        self.tree.set_visible("Docs", True)
        self.tree.set_visible("Docs/nested", True)
        wait_until(lambda: directory(self.tree, "Docs/nested")["items"] is not None)
        self.tree.move_entry("Docs", "archive")
        self.assertFalse(any(d["path"].lower().startswith("docs") for d in self.tree.snapshot()["directories"]))

    @unittest.skipUnless(os.name == "nt", "Windows rename semantics")
    def test_move_discards_an_inflight_scan_for_old_directory(self) -> None:
        (self.root / "old").mkdir()
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        real_scan = scan_dir

        def delayed_scan(path: Path, include_modified: bool = False) -> list[FileTreeItem]:
            if path.name == "old":
                started.set()
                release.wait(5)
            try:
                return real_scan(path, include_modified)
            finally:
                finished.set()

        with patch("backend.services.filesystem.scan_dir", side_effect=delayed_scan):
            self.tree.set_visible("old", True)
            self.assertTrue(started.wait(5))
            try:
                self.tree.move_entry("old", "new")
            finally:
                release.set()
            self.assertTrue(finished.wait(5))
            wait_until(lambda: not any(d["path"] == "old" for d in self.tree.snapshot()["directories"]))

    def test_watcher_create_rename_delete_and_sort(self) -> None:
        self.tree.set_visible("", True)
        wait_until(lambda: directory(self.tree, "")["items"] is not None)
        first = self.root / "z.md"
        first.write_text("one")
        wait_until(
            lambda: any(
                i["name"] == "z.md" for i in (directory(self.tree, "")["items"] or [])
            )
        )
        first.rename(self.root / "a.md")
        wait_until(
            lambda: (
                [i["name"] for i in (directory(self.tree, "")["items"] or [])]
                == ["a.md"]
            )
        )
        self.tree.set_sort("modified")
        wait_until(
            lambda: (
                not directory(self.tree, "")["stale"]
                and any(
                    i["modified_time"] is not None
                    for i in (directory(self.tree, "")["items"] or [])
                )
            )
        )
        (self.root / "a.md").unlink()
        wait_until(lambda: directory(self.tree, "")["items"] == [])

    def test_changes_during_scan_are_rescanned(self) -> None:
        started, release = threading.Event(), threading.Event()
        calls: list[Path] = []

        def delayed(path: Path, include_modified: bool = False) -> list[FileTreeItem]:
            calls.append(path)
            if len(calls) == 1:
                started.set()
                release.wait(3)
            return scan_dir(path, include_modified)

        with patch("backend.services.filesystem.scan_dir", side_effect=delayed):
            self.tree.set_visible("", True)
            self.assertTrue(started.wait(3))
            self.tree.path_changed(self.root / "new.md")
            release.set()
            wait_until(
                lambda: len(calls) >= 2 and not directory(self.tree, "")["stale"]
            )

    def test_watcher_failure_and_refresh(self) -> None:
        self.tree.set_visible("", True)
        wait_until(lambda: directory(self.tree, "")["items"] is not None)
        self.tree.invalidate_all("events lost")
        self.assertEqual(self.tree.snapshot()["watcher_error"], "events lost")
        wait_until(lambda: not directory(self.tree, "")["stale"])

    def test_missing_directory_reports_error_and_retries(self) -> None:
        self.tree.set_visible("missing", True)
        wait_until(lambda: directory(self.tree, "missing")["error"] is not None)
        (self.root / "missing").mkdir()
        self.tree.refresh("missing")
        wait_until(lambda: directory(self.tree, "missing")["items"] == [])

    def test_closed_folder_updates_after_delay(self) -> None:
        (self.root / "folder").mkdir()
        with patch("backend.services.filesystem.CLOSED_DELAY", 0.1):
            self.tree.set_visible("folder", True)
            wait_until(lambda: directory(self.tree, "folder")["items"] == [])
            self.tree.set_visible("folder", False)
            (self.root / "folder" / "added.md").write_text("content")
            wait_until(
                lambda: any(
                    item["name"] == "added.md"
                    for item in (directory(self.tree, "folder")["items"] or [])
                )
            )

    def test_bridge_rejects_previous_workspace(self) -> None:
        bridge = Bridge()
        self.addCleanup(bridge._close)
        first = bridge.open_workspace(str(self.root))["workspace_id"]
        other = self.root / "other"
        other.mkdir()
        second = bridge.open_workspace(str(other))["workspace_id"]
        self.assertNotEqual(first, second)
        with self.assertRaises(ValueError):
            bridge.get_tree(first)

    def test_visible_scan_precedes_queued_closed_scan(self) -> None:
        for name in ("busy1", "busy2", "closed", "open"):
            (self.root / name).mkdir()
        release = threading.Event()
        started: list[str] = []
        lock = threading.Lock()

        def delayed(path: Path, include_modified: bool = False) -> list[FileTreeItem]:
            with lock:
                started.append(path.name)
            if path.name.startswith("busy"):
                release.wait(5)
            return scan_dir(path, include_modified)

        with patch("backend.services.filesystem.scan_dir", side_effect=delayed):
            self.tree.set_visible("busy1", True)
            self.tree.set_visible("busy2", True)
            try:
                wait_until(lambda: len(started) == 2)
                with self.tree._condition:
                    self.tree.set_visible("closed", True)
                    self.tree.set_visible("closed", False)
                    self.tree.set_visible("open", True)
                release.set()
                wait_until(lambda: len(started) == 4)
                self.assertEqual(started[2], "open")
            finally:
                release.set()


if __name__ == "__main__":
    unittest.main()
