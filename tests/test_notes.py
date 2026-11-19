"""Exercise note boundaries, version conflicts, and safe replacement."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.bridge import Bridge, SharedState
from backend.modules.notes import NoteConflictError, read_note, save_note


class NoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.path = self.root / "note.md"
        self.path.write_bytes(b"first\r\n")

    def test_read_and_save_preserve_exact_text(self) -> None:
        note = read_note(self.root, "note.md")
        self.assertEqual(note["content"], "first\r\n")
        saved = save_note(self.root, "note.md", "edited\r\n", note["version"])
        self.assertEqual(read_note(self.root, "note.md"), saved)
        self.assertEqual(self.path.read_bytes(), b"edited\r\n")

    def test_outside_and_non_markdown_paths_are_rejected(self) -> None:
        for path in ("../note.md", str(self.path), "note.txt"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                read_note(self.root, path)

    def test_invalid_utf8_does_not_change_file(self) -> None:
        self.path.write_bytes(b"\xff")
        with self.assertRaises(UnicodeDecodeError):
            read_note(self.root, "note.md")
        self.assertEqual(self.path.read_bytes(), b"\xff")

    def test_symlink_outside_workspace_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "outside.md"
            target.write_text("external", encoding="utf-8")
            try:
                (self.root / "link.md").symlink_to(target)
            except OSError as error:
                self.skipTest(f"Symlink creation unavailable: {error}")
            with self.assertRaises(ValueError):
                read_note(self.root, "link.md")

    def test_changed_or_deleted_file_is_not_overwritten(self) -> None:
        version = read_note(self.root, "note.md")["version"]
        self.path.write_text("external", encoding="utf-8")
        with self.assertRaises(NoteConflictError):
            save_note(self.root, "note.md", "local", version)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "external")
        self.path.unlink()
        with self.assertRaises(NoteConflictError):
            save_note(self.root, "note.md", "local", version)
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_replace_failure_leaves_original_and_cleans_temporary_file(self) -> None:
        version = read_note(self.root, "note.md")["version"]
        with patch("backend.modules.notes.os.replace", side_effect=OSError("failure")):
            with self.assertRaises(OSError):
                save_note(self.root, "note.md", "local", version)
        self.assertEqual(self.path.read_bytes(), b"first\r\n")
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_bridge_rejects_stale_workspace(self) -> None:
        bridge = Bridge()
        self.addCleanup(bridge._close)
        first = bridge.open_workspace(str(self.root))["workspace_id"]
        self.assertEqual(bridge.read_note(first, "note.md")["content"], "first\r\n")
        second = bridge.open_workspace(str(self.root))["workspace_id"]
        with self.assertRaises(ValueError):
            bridge.save_note(first, "note.md", "stale", "anything")
        self.assertEqual(bridge.read_note(second, "note.md")["content"], "first\r\n")

    def test_open_note_content_change_has_its_own_signal(self) -> None:
        class TestWindow:
            def __init__(self) -> None:
                self.values: dict[str, int] = {}
                self.state: SharedState = self.values

            def destroy(self) -> None:
                pass

        bridge = Bridge()
        self.addCleanup(bridge._close)
        window = TestWindow()
        bridge._attach_window(window)
        workspace = bridge.open_workspace(str(self.root))["workspace_id"]
        bridge.read_note(workspace, "note.md")
        bridge.set_active_note(workspace, "note.md")
        self.path.write_text("external", encoding="utf-8")
        deadline = time.monotonic() + 3
        while "note_revision" not in window.values and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIn("note_revision", window.values)
