"""Provide general filesystem and file-tree operations for a workspace."""

import os
from pathlib import Path
from typing import TypedDict


class FileTreeItem(TypedDict):
    name: str
    is_directory: bool
    modified_time: float


def scan_dir(folder: Path) -> list[FileTreeItem]:
    try:
        items: list[FileTreeItem] = []
        with os.scandir(folder) as entries:
            for entry in entries:
                items.append({
                    "name": entry.name,
                    "is_directory": entry.is_dir(),
                    "modified_time": entry.stat().st_mtime,
                })

    except FileNotFoundError as error:
        print("klasör bulunamadı |", error)
        raise

    except NotADirectoryError as error:
        print("verilen yol klasör değil |", error)
        raise

    except PermissionError as error:
        print("klasöre erişim izni yok |", error)
        raise

    return items


def sort_items(items: list[FileTreeItem], sort_mode: str) -> list[FileTreeItem]:
    if sort_mode == "alphabetic":
        return sorted(
            items,
            key=lambda item: item["name"].casefold()
        )

    elif sort_mode == "modified":
        return sorted(
            items,
            key=lambda item: item["modified_time"],
            reverse=True,
        )

    else:
        raise ValueError(f"Unknown sort mode: {sort_mode}")
