"""Manage workspace folders and their settings."""

import json
from pathlib import Path


def default_workspace_settings() -> dict[str, object]:
    """Return a new set of default workspace settings."""
    return {
        "theme": "dark",
        "colors": {},
        "ui_font": ["system-ui"],
        "serif_font": ["serif"],
        "monospace_font": ["monospace"],
        "ui_font_size": 14,
        "serif_font_size": 14,
        "monospace_font_size": 14,
        "attachment_folder": ".attachments",
        "new_notes_folder": ".",
        "deletion_mode": "recycle_bin",
        "trash_bin_folder": None,
        "automatic_link_update": True,
        "separate_excluded_from_index": True,
        "excluded_files": None,
        "excluded_folders": None,
        "not_indexed_files": None,
        "not_indexed_folders": None,
        "homepage": None,
        "last_opened": None,
        "startup_view": "empty",
    }


def workspace_settings_path(workspace_root: Path) -> Path:
    """Return the settings path for an existing workspace directory."""
    root = workspace_root.absolute()
    if not root.exists():
        raise FileNotFoundError(f"Workspace does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Workspace is not a directory: {root}")
    return root / ".acornwiki" / "settings.json"


def show_root(workspace_root: Path) -> None:
    print(workspace_root.absolute())


def validate_workspace_settings(settings: dict[str, object]) -> None:
    """Check settings before accepting them from or writing them to a file."""
    if settings.keys() != default_workspace_settings().keys():
        raise ValueError("Workspace settings contain missing or unknown fields")

    for key in ("theme", "deletion_mode", "startup_view"):
        if not isinstance(settings[key], str):
            raise ValueError(f"{key} must be a string")

    colors = settings["colors"]
    if not isinstance(colors, dict):
        raise ValueError("colors must be an object of color strings")
    for name, color in colors.items():
        if not isinstance(name, str) or not isinstance(color, str):
            raise ValueError("colors must be an object of color strings")

    for key in ("ui_font", "serif_font", "monospace_font"):
        fonts = settings[key]
        if not isinstance(fonts, list):
            raise ValueError(f"{key} must be a list of strings")
        for font in fonts:
            if not isinstance(font, str):
                raise ValueError(f"{key} must be a list of strings")

    for key in ("ui_font_size", "serif_font_size", "monospace_font_size"):
        size = settings[key]
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ValueError(f"{key} must be a positive integer")

    for key in (
        "attachment_folder",
        "new_notes_folder",
        "trash_bin_folder",
        "homepage",
    ):
        value = settings[key]
        if value is None and key in ("trash_bin_folder", "homepage"):
            continue
        if not isinstance(value, str) or not value:
            raise ValueError(f"{key} must be a path string")
        path = Path(value)
        if key in ("attachment_folder", "new_notes_folder") and (
            path.anchor or ".." in path.parts
        ):
            raise ValueError(f"{key} must be workspace-relative")

    if settings["deletion_mode"] not in ("recycle_bin", "permanent", "custom_folder"):
        raise ValueError("Unknown deletion mode")
    if (
        settings["deletion_mode"] == "custom_folder"
        and settings["trash_bin_folder"] is None
    ):
        raise ValueError("A custom trash folder is required")
    if settings["startup_view"] not in ("empty", "homepage", "last_opened"):
        raise ValueError("Unknown startup view")

    for key in ("automatic_link_update", "separate_excluded_from_index"):
        if not isinstance(settings[key], bool):
            raise ValueError(f"{key} must be a boolean")

    for key in (
        "excluded_files",
        "excluded_folders",
        "not_indexed_files",
        "not_indexed_folders",
        "last_opened",
    ):
        paths = settings[key]
        if paths is None:
            continue
        if not isinstance(paths, list):
            raise ValueError(f"{key} must be a list of paths or null")
        for path in paths:
            if not isinstance(path, str) or not path:
                raise ValueError(f"{key} must be a list of paths or null")


def create_workspace_settings(workspace_root: Path) -> None:
    """Create default settings without replacing an existing file."""
    settings_file = workspace_settings_path(workspace_root)
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with settings_file.open("x", encoding="utf-8") as file:
            json.dump(default_workspace_settings(), file, ensure_ascii=False, indent=4)
            file.write("\n")
    except FileExistsError:
        return


def load_workspace_settings(workspace_root: Path) -> dict[str, object]:
    """Load workspace settings, or return defaults if the file is absent."""
    settings_file = workspace_settings_path(workspace_root)
    try:
        content = settings_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default_workspace_settings()

    settings: object = json.loads(content)
    if not isinstance(settings, dict):
        raise ValueError("Workspace settings must be a JSON object")
    validate_workspace_settings(settings)
    return settings


def save_workspace_settings(workspace_root: Path, settings: dict[str, object]) -> None:
    """Validate and save workspace settings as JSON."""
    settings_file = workspace_settings_path(workspace_root)
    validate_workspace_settings(settings)
    content = json.dumps(settings, ensure_ascii=False, indent=4)
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(content + "\n", encoding="utf-8")
