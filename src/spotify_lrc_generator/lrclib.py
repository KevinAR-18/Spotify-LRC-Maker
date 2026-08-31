from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_URL = "https://lrclib.net/api/search"


class LrcLibError(RuntimeError):
    pass


@dataclass(frozen=True)
class LrcLibCandidate:
    track_name: str
    artist_name: str
    album_name: str
    duration_seconds: float
    plain_lyrics: str | None
    synced_lyrics: str | None
    instrumental: bool

    @property
    def is_synced(self) -> bool:
        return bool(self.synced_lyrics)


def search(track_name: str, artist_name: str, duration_seconds: float | None = None) -> list[LrcLibCandidate]:
    if not track_name.strip():
        return []
    request = Request(
        f"{API_URL}?{urlencode({'track_name': track_name.strip(), 'artist_name': artist_name.strip()})}",
        headers={"User-Agent": "Spotify-LRC-Maker/1.2.0 (desktop lyric editor)"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        message = "LRCLIB is rate limiting requests. Please try again shortly." if exc.code == 429 else f"LRCLIB returned HTTP {exc.code}."
        raise LrcLibError(message) from exc
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LrcLibError("Unable to reach LRCLIB. Check your connection and try again.") from exc
    candidates = [candidate for item in payload if isinstance(item, dict) if (candidate := _candidate(item))]
    if duration_seconds:
        candidates.sort(key=lambda item: abs(item.duration_seconds - duration_seconds))
    return candidates


def _candidate(item: dict) -> LrcLibCandidate | None:
    track_name = str(item.get("trackName") or "").strip()
    if not track_name:
        return None
    return LrcLibCandidate(
        track_name=track_name,
        artist_name=str(item.get("artistName") or "").strip(),
        album_name=str(item.get("albumName") or "").strip(),
        duration_seconds=float(item.get("duration") or 0),
        plain_lyrics=item.get("plainLyrics") or None,
        synced_lyrics=item.get("syncedLyrics") or None,
        instrumental=bool(item.get("instrumental")),
    )
