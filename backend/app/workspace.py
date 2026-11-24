"""Manage workspace folders and their settings."""

import json
import os
import re
import tempfile
from pathlib import Path
from typing import cast


def default_workspace_settings() -> dict[str, object]:
    """Return a new set of default workspace settings."""
    return {
        "appearance": default_workspace_appearance(),
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


def default_workspace_appearance() -> dict[str, object]:
    """Return a new set of default workspace appearance settings."""
    return {
        "theme": "warm-charcoal",
        "surface_mode": "seamless",
        "page_width": "96ch",
        "fonts": {
            "ui": ["system-ui"],
            "body": ["serif"],
            "monospace": ["monospace"],
        },
        "font_sizes": {"ui": 14, "body": 16, "monospace": 14},
        "font_weights": {"ui": 400, "body": 400, "monospace": 400},
        "theme_overrides": {},
        "custom_themes": {},
        "file_icons": {"set": "minimal", "extensions": {}},
    }


def _object_with_string_keys(value: object) -> dict[str, object] | None:
    """Return a string-keyed dictionary, or None for non-object input."""
    if not isinstance(value, dict):
        return None
    result: dict[str, object] = {}
    # Validate keys while treating all dictionary values as ordinary objects.
    for key, item in cast(dict[object, object], value).items():
        if not isinstance(key, str):
            return None
        result[key] = item
    return result


def _object_list(value: object) -> list[object] | None:
    """Return a list of objects, or None for non-list input."""
    if not isinstance(value, list):
        return None
    # Every Python list item is an object and its type is checked by the caller.
    return cast(list[object], value)


def workspace_settings_path(workspace_root: Path) -> Path:
    """Return the settings path for an existing workspace directory."""
    root = workspace_root.resolve(strict=True)
    if not root.exists():
        raise FileNotFoundError(f"Workspace does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Workspace is not a directory: {root}")
    settings_file = root / ".acornwiki" / "settings.json"
    if not settings_file.resolve().is_relative_to(root):
        raise ValueError("Workspace settings must stay inside the workspace")
    return settings_file


def show_root(workspace_root: Path) -> None:
    print(workspace_root.absolute())


def validate_workspace_settings(settings: dict[str, object]) -> None:
    """Check settings before accepting them from or writing them to a file."""
    if settings.keys() != default_workspace_settings().keys():
        raise ValueError("Workspace settings contain missing or unknown fields")

    appearance = _object_with_string_keys(settings["appearance"])
    if appearance is None:
        raise ValueError("appearance must be an object")
    validate_workspace_appearance(appearance)

    for key in ("deletion_mode", "startup_view"):
        if not isinstance(settings[key], str):
            raise ValueError(f"{key} must be a string")

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
        path_items = _object_list(paths)
        if path_items is None or any(
            not isinstance(path, str) or not path for path in path_items
        ):
            raise ValueError(f"{key} must be a list of paths or null")


def validate_workspace_appearance(appearance: dict[str, object]) -> None:
    """Check appearance settings loaded from a workspace file."""
    if appearance.keys() != default_workspace_appearance().keys():
        raise ValueError("appearance contains missing or unknown fields")

    theme = appearance["theme"]
    if not isinstance(theme, str) or not theme:
        raise ValueError("appearance.theme must be a non-empty string")
    if appearance["surface_mode"] not in ("framed", "seamless"):
        raise ValueError("Unknown appearance surface mode")

    page_width = appearance["page_width"]
    if not isinstance(page_width, str):
        raise ValueError("appearance.page_width must be a CSS width")
    width_match = re.fullmatch(r"(\d+(?:\.\d+)?)(ch|rem|px|vw|%)", page_width)
    if width_match is None or float(width_match.group(1)) <= 0:
        raise ValueError("appearance.page_width must be a positive CSS width")

    fonts = _object_with_string_keys(appearance["fonts"])
    if fonts is None or fonts.keys() != {"ui", "body", "monospace"}:
        raise ValueError("appearance.fonts must contain ui, body, and monospace")
    for name, raw_stack in fonts.items():
        stack = _object_list(raw_stack)
        if stack is None or any(not isinstance(font, str) for font in stack):
            raise ValueError(f"appearance.fonts.{name} must be a list of strings")

    font_sizes = _object_with_string_keys(appearance["font_sizes"])
    if font_sizes is None or font_sizes.keys() != {"ui", "body", "monospace"}:
        raise ValueError("appearance.font_sizes must contain ui, body, and monospace")
    for name, size in font_sizes.items():
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ValueError(f"appearance.font_sizes.{name} must be a positive integer")

    font_weights = _object_with_string_keys(appearance["font_weights"])
    if font_weights is None or font_weights.keys() != {"ui", "body", "monospace"}:
        raise ValueError("appearance.font_weights must contain ui, body, and monospace")
    for name, weight in font_weights.items():
        if isinstance(weight, bool) or not isinstance(weight, int) or not (100 <= weight <= 900):
            raise ValueError(f"appearance.font_weights.{name} must be an integer between 100 and 900")

    overrides = _object_with_string_keys(appearance["theme_overrides"])
    if overrides is None:
        raise ValueError("appearance.theme_overrides must be an object")
    for name, raw_colors in overrides.items():
        colors = _object_with_string_keys(raw_colors)
        if colors is None:
            raise ValueError("appearance.theme_overrides must map themes to colors")
        if any(
            not isinstance(token, str) or not isinstance(color, str)
            for token, color in colors.items()
        ):
            raise ValueError("appearance theme overrides must contain color strings")

    custom_themes = _object_with_string_keys(appearance["custom_themes"])
    if custom_themes is None:
        raise ValueError("appearance.custom_themes must be an object")
    if any(
        _object_with_string_keys(theme_data) is None
        for theme_data in custom_themes.values()
    ):
        raise ValueError("appearance.custom_themes must map theme names to objects")

    file_icons = _object_with_string_keys(appearance["file_icons"])
    if (
        file_icons is None
        or file_icons.keys() != {"set", "extensions"}
        or not isinstance(file_icons["set"], str)
        or not file_icons["set"]
    ):
        raise ValueError(
            "appearance.file_icons must contain an icon set and extensions"
        )
    extensions = _object_with_string_keys(file_icons["extensions"])
    if extensions is None:
        raise ValueError(
            "appearance.file_icons must contain an icon set and extensions"
        )
    if any(
        not isinstance(extension, str) or not isinstance(icon, str)
        for extension, icon in extensions.items()
    ):
        raise ValueError("appearance file icon overrides must map extensions to icons")


def update_workspace_appearance(workspace_root: Path, patch: object) -> None:
    """Merge a partial appearance update and save the workspace settings."""
    defaults = default_workspace_appearance()
    appearance_patch = _object_with_string_keys(patch)
    if appearance_patch is None or not appearance_patch:
        raise ValueError("appearance must be a non-empty object")
    if any(name not in defaults for name in appearance_patch):
        raise ValueError("appearance contains unknown fields")

    settings = load_workspace_settings(workspace_root)
    appearance = _object_with_string_keys(settings["appearance"])
    if appearance is None:
        raise ValueError("Invalid workspace appearance")
    appearance.update(appearance_patch)
    settings["appearance"] = appearance
    save_workspace_settings(workspace_root, settings)


def create_workspace_settings(workspace_root: Path) -> None:
    """Create default settings without replacing an existing file."""
    settings_file = workspace_settings_path(workspace_root)
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids replacing settings created by another call.
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

    settings = _object_with_string_keys(json.loads(content))
    if settings is None:
        raise ValueError("Workspace settings must be a JSON object")
    appearance = _object_with_string_keys(settings.get("appearance"))
    if appearance is not None and "font_weights" not in appearance:
        appearance["font_weights"] = {"ui": 400, "body": 400, "monospace": 400}
        settings["appearance"] = appearance
    validate_workspace_settings(settings)
    return settings


def save_workspace_settings(workspace_root: Path, settings: dict[str, object]) -> None:
    """Validate and save workspace settings as JSON."""
    settings_file = workspace_settings_path(workspace_root)
    validate_workspace_settings(settings)
    content = json.dumps(settings, ensure_ascii=False, indent=4)
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=settings_file.parent, delete=False
        ) as file:
            temporary = file.name
            file.write(content + "\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, settings_file)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)
