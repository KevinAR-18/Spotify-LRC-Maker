from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative_path: str) -> Path:
    relative = Path(relative_path)
    candidates: list[Path] = []

    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        candidates.append(Path(bundled_root) / relative)

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / relative)

    candidates.append(Path(__file__).resolve().parents[2] / relative)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]
