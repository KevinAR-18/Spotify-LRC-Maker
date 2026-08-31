from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from spotify_lrc_generator.lrc import LyricLine, export_lrc, parse_lrc


def read_lrc_file(path: Path) -> list[LyricLine]:
    for encoding in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            return parse_lrc(path.read_text(encoding=encoding))
        except UnicodeError:
            continue
    raise UnicodeError("The file is not valid UTF-8 or UTF-16 text.")


def write_lrc_file(path: Path, lines: list[LyricLine]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = export_lrc(lines)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class RecoveryStore:
    def __init__(self, root: Path) -> None:
        self.path = root / "recovery-draft.json"

    def save(self, lines: list[LyricLine], path: Path | None, current_index: int, offset_ms: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "lines": [{"text": line.text, "timestamp_ms": line.timestamp_ms, "line_id": line.line_id} for line in lines],
            "path": str(path) if path else None,
            "current_index": current_index,
            "offset_ms": offset_ms,
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def load(self) -> tuple[list[LyricLine], Path | None, int, int] | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            lines = [LyricLine(**line) for line in payload["lines"]]
            path = Path(payload["path"]) if payload.get("path") else None
            return lines, path, int(payload.get("current_index", 0)), int(payload.get("offset_ms", 0))
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
