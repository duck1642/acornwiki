"""Manage application settings and the persistent list of workspace paths."""

import json
import os
import tempfile
from pathlib import Path

SETTINGS_PATH: Path = Path.home() / "acornwiki" / "settings.json"


def default_settings() -> dict[str, object]:
    """Return a new set of default application settings."""
    return {
        "language": "en",
        "workspaces": [],
        "editor": default_editor_settings(),
    }


def default_editor_settings() -> dict[str, bool]:
    """Return the default saving and external-change preferences."""
    return {"autosave": False, "auto_reload": True, "reload_notice": True}


def validate_settings(settings: dict[str, object]) -> None:
    """Check application settings before reading or writing them."""
    if settings.keys() != default_settings().keys():
        raise ValueError("Settings must contain language and workspaces")

    if not isinstance(settings["language"], str):
        raise ValueError("language must be a string")

    workspaces = settings["workspaces"]
    if not isinstance(workspaces, list):
        raise ValueError("workspaces must be a list of strings")
    for workspace in workspaces:
        if not isinstance(workspace, str):
            raise ValueError("workspaces must be a list of strings")

    editor = settings["editor"]
    if not isinstance(editor, dict) or editor.keys() != default_editor_settings().keys():
        raise ValueError("editor must contain the known editor preferences")
    if any(not isinstance(value, bool) for value in editor.values()):
        raise ValueError("editor preferences must be booleans")


def create_settings(path: Path) -> None:
    """Create default settings if the file does not already exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves an existing settings file, even if it appears between creating the parent directory and opening the file.
    try:
        with path.open("x", encoding="utf-8") as file:
            json.dump(default_settings(), file, indent=4)
            file.write("\n")
    except FileExistsError:
        return


def save_settings(path: Path, settings: dict[str, object]) -> None:
    """Save application settings as JSON."""
    validate_settings(settings)
    content = json.dumps(settings, ensure_ascii=False, indent=4)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        # Keep the old settings file intact if serialization or writing fails.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as file:
            temporary = file.name
            file.write(content + "\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)


def load_settings(path: Path) -> dict[str, object]:
    """Load application settings, or return defaults if the file is absent."""
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default_settings()

    data: object = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("Settings must be a JSON object")
    # Existing settings predate the editor field; keep all other fields intact.
    if "editor" not in data:
        data["editor"] = default_editor_settings()
    validate_settings(data)
    return data
