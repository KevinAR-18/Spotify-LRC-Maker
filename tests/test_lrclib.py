import json
from unittest.mock import patch

from spotify_lrc_generator.lrclib import search


class FakeResponse:
    def __init__(self, payload: list[dict]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def test_lrclib_search_maps_and_sorts_candidates_by_duration() -> None:
    payload = [
        {"trackName": "Song", "artistName": "Artist", "duration": 240, "plainLyrics": "Far"},
        {"trackName": "Song", "artistName": "Artist", "duration": 180, "syncedLyrics": "[00:01.00]Near"},
    ]
    with patch("spotify_lrc_generator.lrclib.urlopen", return_value=FakeResponse(payload)):
        candidates = search("Song", "Artist", 181)

    assert [candidate.duration_seconds for candidate in candidates] == [180, 240]
    assert candidates[0].is_synced
