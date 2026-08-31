from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from uuid import uuid4


@dataclass
class LyricLine:
    text: str
    timestamp_ms: int | None = None
    line_id: str = field(default_factory=lambda: uuid4().hex, compare=False)


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    message: str
    line_index: int | None = None


LRC_LINE_PATTERN = re.compile(r"^\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?](.*)$")


def clone_lines(lines: list[LyricLine]) -> list[LyricLine]:
    return [LyricLine(line.text, line.timestamp_ms, line.line_id) for line in lines]


def parse_plain_lyrics(text: str) -> list[LyricLine]:
    return [LyricLine(line.strip()) for line in text.splitlines() if line.strip()]


def parse_lrc(text: str) -> list[LyricLine]:
    lines: list[LyricLine] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = LRC_LINE_PATTERN.match(line)
        if not match:
            lines.append(LyricLine(line))
            continue
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        fraction = match.group(3) or "0"
        lyric = match.group(4).strip()
        milliseconds = int(fraction.ljust(3, "0")[:3])
        timestamp_ms = (minutes * 60 + seconds) * 1000 + milliseconds
        lines.append(LyricLine(lyric, timestamp_ms))
    return lines


def merge_editor_lines(existing: list[LyricLine], text: str) -> list[LyricLine]:
    """Keep line identities and timestamps for unchanged text subsequences."""
    edited = [line.strip() for line in text.splitlines() if line.strip()]
    result: list[LyricLine] = []
    matcher = SequenceMatcher(
        a=[line.text for line in existing], b=edited, autojunk=False
    )
    matched: dict[int, LyricLine] = {}
    for old_start, new_start, size in matcher.get_matching_blocks():
        for offset in range(size):
            matched[new_start + offset] = existing[old_start + offset]
    for index, line_text in enumerate(edited):
        previous = matched.get(index)
        result.append(
            LyricLine(line_text, previous.timestamp_ms, previous.line_id)
            if previous is not None
            else LyricLine(line_text)
        )
    return result


def format_timestamp(timestamp_ms: int) -> str:
    total_centiseconds = (max(timestamp_ms, 0) + 5) // 10
    total_seconds, centiseconds = divmod(total_centiseconds, 100)
    minutes, seconds = divmod(total_seconds, 60)
    return f"[{minutes:02d}:{seconds:02d}.{centiseconds:02d}]"


def format_position(timestamp_ms: int | None) -> str:
    return "--:--.--" if timestamp_ms is None else format_timestamp(timestamp_ms).strip("[]")


def shift_timestamp(timestamp_ms: int | None, delta_ms: int) -> int | None:
    return None if timestamp_ms is None else max(0, timestamp_ms + delta_ms)


def export_lrc(lines: list[LyricLine]) -> str:
    stamped = [
        f"{format_timestamp(line.timestamp_ms)}{line.text}"
        for line in lines
        if line.timestamp_ms is not None and line.text.strip()
    ]
    return "\n".join(stamped) + ("\n" if stamped else "")


def count_unstamped(lines: list[LyricLine]) -> int:
    return sum(1 for line in lines if line.text.strip() and line.timestamp_ms is None)


def validate_lines(lines: list[LyricLine], duration_ms: int | None = None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not lines:
        return [ValidationIssue("error", "There are no lyric lines to export.")]
    previous_timestamp: int | None = None
    for index, line in enumerate(lines):
        if not line.text.strip():
            issues.append(ValidationIssue("error", "Lyric text is empty.", index))
        if line.timestamp_ms is None:
            issues.append(ValidationIssue("warning", "Line has no timestamp and will be skipped.", index))
            continue
        if previous_timestamp is not None and line.timestamp_ms < previous_timestamp:
            issues.append(ValidationIssue("warning", "Timestamp is earlier than the previous line.", index))
        if previous_timestamp == line.timestamp_ms:
            issues.append(ValidationIssue("warning", "Timestamp duplicates the previous line.", index))
        if duration_ms and line.timestamp_ms > duration_ms:
            issues.append(ValidationIssue("warning", "Timestamp is beyond the current track duration.", index))
        previous_timestamp = line.timestamp_ms
    return issues
