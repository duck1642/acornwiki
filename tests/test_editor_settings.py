"""Check editor preferences against existing application settings."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.bridge import Bridge
from backend.app.settings import load_settings


class EditorSettingsTests(unittest.TestCase):
    def test_old_settings_are_preserved_when_preference_is_saved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"language": "tr", "workspaces": ["example"]}))
            bridge = Bridge()
            self.addCleanup(bridge._close)
            with patch("backend.app.bridge.SETTINGS_PATH", path):
                editor = bridge.get_settings()["editor"]
                assert isinstance(editor, dict)
                self.assertFalse(editor["autosave"])
                bridge.set_editor_preference("autosave", True)
                settings = load_settings(path)
                self.assertEqual(settings["language"], "tr")
                self.assertEqual(settings["workspaces"], ["example"])
                editor = settings["editor"]
                assert isinstance(editor, dict)
                self.assertTrue(editor["autosave"])

    def test_failed_replacement_preserves_old_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            original = '{"language": "tr", "workspaces": []}'
            path.write_text(original)
            bridge = Bridge()
            self.addCleanup(bridge._close)
            with patch("backend.app.bridge.SETTINGS_PATH", path):
                with patch("backend.app.settings.os.replace", side_effect=OSError):
                    with self.assertRaises(OSError):
                        bridge.set_editor_preference("autosave", True)
            self.assertEqual(path.read_text(), original)
            self.assertEqual(list(path.parent.iterdir()), [path])
