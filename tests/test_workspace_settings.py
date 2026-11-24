"""Check workspace appearance settings and their bridge update path."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.bridge import Bridge
from backend.app.workspace import (
    create_workspace_settings,
    default_workspace_settings,
    load_workspace_settings,
    save_workspace_settings,
)


class WorkspaceSettingsTests(unittest.TestCase):
    def test_new_items_folder_and_recursive_search(self) -> None:
        directory = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(directory)
        (root / "nested").mkdir()
        (root / "nested" / "Example.md").write_text("test", encoding="utf-8")
        bridge = Bridge()
        self.addCleanup(bridge._close)
        workspace_id = bridge.open_workspace(str(root))["workspace_id"]
        self.addCleanup(lambda: bridge.close_workspace(workspace_id))
        bridge.set_new_items_folder(workspace_id, "nested")
        self.assertEqual(load_workspace_settings(root)["new_notes_folder"], "nested")
        self.assertEqual(bridge.create_note(workspace_id, "nested", "New"), "nested/New.md")
        self.assertEqual(bridge.search_workspace(workspace_id, "example")["items"], [{"path": "nested/Example.md", "is_directory": False}])
        with self.assertRaises((ValueError, FileNotFoundError)):
            bridge.set_new_items_folder(workspace_id, "../outside")
        self.assertEqual(load_workspace_settings(root)["new_notes_folder"], "nested")

    def test_defaults_include_workspace_appearance(self) -> None:
        settings = default_workspace_settings()
        appearance = settings["appearance"]
        assert isinstance(appearance, dict)
        self.assertEqual(appearance["theme"], "warm-charcoal")
        self.assertEqual(appearance["surface_mode"], "framed")
        self.assertEqual(appearance["page_width"], "74ch")
        self.assertEqual(appearance["file_icons"], {"set": "minimal", "extensions": {}})

    def test_unknown_theme_and_icon_set_ids_are_preserved(self) -> None:
        directory = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(directory)
        create_workspace_settings(root)
        settings = load_workspace_settings(root)
        appearance = settings["appearance"]
        assert isinstance(appearance, dict)
        appearance["theme"] = "third-party-theme"
        appearance["file_icons"] = {"set": "third-party-icons", "extensions": {}}
        save_workspace_settings(root, settings)

        loaded = load_workspace_settings(root)
        loaded_appearance = loaded["appearance"]
        assert isinstance(loaded_appearance, dict)
        self.assertEqual(loaded_appearance["theme"], "third-party-theme")
        self.assertEqual(
            loaded_appearance["file_icons"],
            {"set": "third-party-icons", "extensions": {}},
        )

    def test_bridge_updates_appearance_and_preserves_other_settings(self) -> None:
        directory = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(directory)
        create_workspace_settings(root)
        settings = load_workspace_settings(root)
        settings["automatic_link_update"] = False
        settings["attachment_folder"] = "assets"
        save_workspace_settings(root, settings)

        bridge = Bridge()
        self.addCleanup(bridge._close)
        snapshot = bridge.open_workspace(str(root))
        self.addCleanup(lambda: bridge.close_workspace(snapshot["workspace_id"]))

        bridge.set_workspace_appearance(
            snapshot["workspace_id"],
            {"theme": "warm-paper", "surface_mode": "seamless"},
        )

        updated = load_workspace_settings(root)
        appearance = updated["appearance"]
        assert isinstance(appearance, dict)
        self.assertEqual(appearance["theme"], "warm-paper")
        self.assertEqual(appearance["surface_mode"], "seamless")
        self.assertEqual(appearance["page_width"], "74ch")
        self.assertFalse(updated["automatic_link_update"])
        self.assertEqual(updated["attachment_folder"], "assets")

    def test_appearance_update_rejects_workspace_id_from_another_context(self) -> None:
        directory = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(directory)
        create_workspace_settings(root)
        original = (root / ".acornwiki" / "settings.json").read_text(encoding="utf-8")

        bridge = Bridge()
        self.addCleanup(bridge._close)
        snapshot = bridge.open_workspace(str(root))
        self.addCleanup(lambda: bridge.close_workspace(snapshot["workspace_id"]))

        with self.assertRaisesRegex(ValueError, "no longer active"):
            bridge.set_workspace_appearance(
                "another-workspace", {"theme": "warm-paper"}
            )

        self.assertEqual(
            (root / ".acornwiki" / "settings.json").read_text(encoding="utf-8"),
            original,
        )

    def test_failed_appearance_replacement_preserves_previous_file(self) -> None:
        directory = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(directory)
        create_workspace_settings(root)
        path = root / ".acornwiki" / "settings.json"
        original = path.read_text(encoding="utf-8")
        bridge = Bridge()
        self.addCleanup(bridge._close)
        snapshot = bridge.open_workspace(str(root))
        self.addCleanup(lambda: bridge.close_workspace(snapshot["workspace_id"]))

        with patch("backend.app.workspace.os.replace", side_effect=OSError):
            with self.assertRaises(OSError):
                bridge.set_workspace_appearance(
                    snapshot["workspace_id"], {"theme": "warm-paper"}
                )

        self.assertEqual(path.read_text(encoding="utf-8"), original)
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_workspace_settings_reject_unknown_appearance_fields(self) -> None:
        settings = default_workspace_settings()
        appearance = settings["appearance"]
        assert isinstance(appearance, dict)
        appearance["future_field"] = True
        directory = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(directory)
        path = root / ".acornwiki" / "settings.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(settings), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "appearance contains"):
            load_workspace_settings(root)

    def test_font_weights_defaults_and_legacy_file_compatibility(self) -> None:
        directory = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(directory)
        legacy = default_workspace_settings()
        appearance = legacy["appearance"]
        assert isinstance(appearance, dict)
        del appearance["font_weights"]
        path = root / ".acornwiki" / "settings.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(legacy), encoding="utf-8")

        loaded = load_workspace_settings(root)
        loaded_appearance = loaded["appearance"]
        assert isinstance(loaded_appearance, dict)
        self.assertEqual(loaded_appearance["font_weights"], {"ui": 400, "body": 400, "monospace": 400})

        bridge = Bridge()
        self.addCleanup(bridge._close)
        snapshot = bridge.open_workspace(str(root))
        self.addCleanup(lambda: bridge.close_workspace(snapshot["workspace_id"]))
        bridge.set_workspace_appearance(
            snapshot["workspace_id"],
            {"font_weights": {"ui": 500, "body": 400, "monospace": 500}},
        )
        updated = load_workspace_settings(root)["appearance"]
        assert isinstance(updated, dict)
        self.assertEqual(updated["font_weights"], {"ui": 500, "body": 400, "monospace": 500})
