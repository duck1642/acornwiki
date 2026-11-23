"""Exercise note boundaries, version conflicts, and safe replacement."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from backend.app.bridge import Bridge, SharedState
from backend.modules.notes import (
    NoteConflictError,
    list_markdown_notes,
    markdown_name,
    read_note,
    resolve_note_link,
    save_note,
)
from backend.services.media import MediaServer


class NoteTests(unittest.TestCase):
    def test_markdown_extension_as_filename_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".md").write_text("note", encoding="utf-8")
            self.assertEqual(read_note(root, ".md")["content"], "note")
            self.assertEqual(list_markdown_notes(root), [".md"])
        for name in (".md", ".MD"):
            with self.subTest(name=name):
                self.assertEqual(markdown_name(name), name)
        self.assertEqual(markdown_name("note"), "note.md")

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

    def test_relative_links_stay_within_workspace(self) -> None:
        (self.root / "nested").mkdir()
        note = "nested/note.md"
        self.assertEqual(
            resolve_note_link(self.root, note, "../images/a%20b.png"),
            ("images/a b.png", ""),
        )
        self.assertEqual(resolve_note_link(self.root, note, "#my-heading"), (note, "my-heading"))
        for href in (
            "../../outside.png", "https://example.com/a", "C:/test.png",
            "..%2F..%2Foutside.png",
        ):
            with self.subTest(href=href), self.assertRaises(ValueError):
                resolve_note_link(self.root, note, href)

    def test_media_server_uses_active_workspace_and_serves_images(self) -> None:
        image = self.root / "image.png"
        image.write_bytes(b"image bytes")
        bridge = Bridge()
        self.addCleanup(bridge._close)
        workspace = bridge.open_workspace(str(self.root))["workspace_id"]
        server = MediaServer(bridge._resolve_media)
        self.addCleanup(server.close)

        def url(src: str, workspace_id: str = workspace) -> str:
            return server.url + "?" + urlencode(
                {"workspace": workspace_id, "note": "note.md", "src": src}
            )

        with urlopen(url("image.png")) as result:
            self.assertEqual(result.headers.get_content_type(), "image/png")
            self.assertEqual(result.read(), b"image bytes")
        for address in (url("../image.png"), url("note.md"), url("image.png", "old")):
            with self.subTest(address=address), self.assertRaises(HTTPError) as error:
                urlopen(address)
            self.assertEqual(error.exception.code, 404)

    def test_nested_note_resolves_unicode_images_and_rejects_missing_targets(self) -> None:
        nested = self.root / "notes"
        nested.mkdir()
        (nested / "günlük.md").write_text("test", encoding="utf-8")
        image_dir = self.root / "görseller"
        image_dir.mkdir()
        (image_dir / "bir resim.png").write_bytes(b"image")
        bridge = Bridge()
        self.addCleanup(bridge._close)
        workspace = bridge.open_workspace(str(self.root))["workspace_id"]
        server = MediaServer(bridge._resolve_media)
        self.addCleanup(server.close)

        def request(src: str) -> str:
            return server.url + "?" + urlencode(
                {"workspace": workspace, "note": "notes/günlük.md", "src": src}
            )

        with urlopen(request("../görseller/bir%20resim.png")) as response:
            self.assertEqual(response.read(), b"image")
        for src in ("../görseller/yok.png", "../../outside.png", "../görseller/%00.png"):
            with self.subTest(src=src), self.assertRaises(HTTPError) as error:
                urlopen(request(src))
            self.assertEqual(error.exception.code, 404)

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

    def test_local_file_opens_only_from_active_workspace(self) -> None:
        document = self.root / "guide.pdf"
        document.write_bytes(b"pdf")
        bridge = Bridge()
        self.addCleanup(bridge._close)
        workspace = bridge.open_workspace(str(self.root))["workspace_id"]
        with patch("backend.app.bridge.os.startfile", create=True) as open_file:
            with patch("backend.app.bridge.sys.platform", "win32"):
                bridge.open_workspace_file(workspace, "guide.pdf")
                open_file.assert_called_once_with(document)
                for invalid in ("../outside.pdf", "missing.pdf"):
                    with self.subTest(invalid=invalid), self.assertRaises((ValueError, OSError)):
                        bridge.open_workspace_file(workspace, invalid)
                with self.assertRaises(ValueError):
                    bridge.open_workspace_file("old", "guide.pdf")
                open_file.assert_called_once()

    def test_blocked_file_is_not_opened_and_can_be_revealed(self) -> None:
        script = self.root / "run.EXE"
        script.write_bytes(b"")
        bridge = Bridge()
        self.addCleanup(bridge._close)
        workspace = bridge.open_workspace(str(self.root))["workspace_id"]
        settings = self.root / "app-settings.json"
        with patch("backend.app.bridge.SETTINGS_PATH", settings):
            with patch("backend.app.bridge.sys.platform", "win32"):
                with patch("backend.app.bridge.os.startfile", create=True) as open_file:
                    self.assertFalse(bridge.open_workspace_file(workspace, "run.EXE"))
                    open_file.assert_not_called()
                    with patch("backend.app.bridge.subprocess.Popen") as launch:
                        bridge.reveal_workspace_file(workspace, "run.EXE")
                        launch.assert_called_once_with(["explorer.exe", "/select,", str(script)])
                    bridge.set_blocked_extensions([".bat"])
                    self.assertTrue(bridge.open_workspace_file(workspace, "run.EXE"))
                    open_file.assert_called_once_with(script)

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
