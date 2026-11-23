"""Start the application with a separate workspace for manual testing."""

import json
from pathlib import Path

import backend.app.bridge as bridge
from backend.app.settings import default_settings
import start


def main() -> None:
    """Create the test environment once and start the development application."""
    test_root = Path(__file__).resolve().parent / "tmp" / "interface-iteration"
    workspace = test_root / "workspace"
    settings_path = test_root / "settings.json"

    # Preserve an existing test workspace and all edits made during previous runs.
    if not workspace.exists():
        (workspace / "notes").mkdir(parents=True)
        (workspace / "Welcome.md").write_text(
            "# Welcome\n\nThis workspace is for testing the interface.\n",
            encoding="utf-8",
        )
        (workspace / "notes" / "Sample.md").write_text(
            "# Sample note\n\nEdit and save this note while testing.\n",
            encoding="utf-8",
        )
    if not settings_path.exists():
        settings = default_settings()
        settings["workspaces"] = [str(workspace)]
        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    bridge.SETTINGS_PATH = settings_path
    start.main()


if __name__ == "__main__":
    main()
