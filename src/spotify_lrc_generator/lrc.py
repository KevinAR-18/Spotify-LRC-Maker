from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass
class LyricLine:
    text: str
    timestamp_ms: int | None = None


LRC_LINE_PATTERN = re.compile(r"^\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?](.*)$")


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
        if len(fraction) == 1:
            milliseconds = int(fraction) * 100
        elif len(fraction) == 2:
            milliseconds = int(fraction) * 10
        else:
            milliseconds = int(fraction[:3])
        timestamp_ms = (minutes * 60 + seconds) * 1000 + milliseconds
        lines.append(LyricLine(lyric, timestamp_ms))
    return lines


def format_timestamp(timestamp_ms: int) -> str:
    if timestamp_ms < 0:
        timestamp_ms = 0

    total_centiseconds = (timestamp_ms + 5) // 10
    total_seconds, centiseconds = divmod(total_centiseconds, 100)
    minutes, seconds = divmod(total_seconds, 60)
    return f"[{minutes:02d}:{seconds:02d}.{centiseconds:02d}]"


def format_position(timestamp_ms: int | None) -> str:
    if timestamp_ms is None:
        return "--:--.--"
    return format_timestamp(timestamp_ms).strip("[]")


def shift_timestamp(timestamp_ms: int | None, delta_ms: int) -> int:
    base = 0 if timestamp_ms is None else timestamp_ms
    return max(0, base + delta_ms)


def export_lrc(lines: list[LyricLine]) -> str:
    stamped = [
        f"{format_timestamp(line.timestamp_ms)}{line.text}"
        for line in lines
        if line.timestamp_ms is not None and line.text.strip()
    ]
    return "\n".join(stamped) + ("\n" if stamped else "")


def count_unstamped(lines: list[LyricLine]) -> int:
    return sum(1 for line in lines if line.text.strip() and line.timestamp_ms is None)
