"""Translate PyWebView API calls into backend operations."""

from pathlib import Path

from backend.app.settings import SETTINGS_PATH, load_settings
from backend.app.workspace import load_workspace_settings
from backend.services.filesystem import FileTreeItem, scan_dir, sort_items


class Bridge:
    """Expose backend operations to the frontend through PyWebView."""

    def ping(self) -> str:
        """Return a simple response to check the bridge connection."""
        return "Backend çalışıyor"

    def get_settings(self) -> dict[str, object]:
        """Return application settings or their defaults."""
        return load_settings(SETTINGS_PATH)

    def get_workspace_settings(self, workspace_root: str) -> dict[str, object]:
        """Return the settings of the given workspace directory."""
        if not isinstance(workspace_root, str) or not workspace_root.strip():
            raise ValueError("workspace_root must be a non-empty path string")
        return load_workspace_settings(Path(workspace_root))

    def get_directory_items(
        self,
        workspace_root: str,
        relative_path: str,
        sort_mode: str,
    ) -> list[FileTreeItem]:
        """Return sorted direct children of a workspace-relative directory."""
        if not isinstance(workspace_root, str) or not workspace_root.strip():
            raise ValueError("workspace_root must be a non-empty path string")
        if not isinstance(relative_path, str):
            raise TypeError("relative_path must be a string")
        if not isinstance(sort_mode, str):
            raise TypeError("sort_mode must be a string")

        root = Path(workspace_root).resolve()
        relative_folder = Path(relative_path)
        if relative_folder.is_absolute() or ".." in relative_folder.parts:
            raise ValueError("relative_path must stay inside the workspace")

        folder = (root / relative_folder).resolve()
        try:
            folder.relative_to(root)
        except ValueError as error:
            raise ValueError("relative_path must stay inside the workspace") from error

        return sort_items(scan_dir(folder), sort_mode)
