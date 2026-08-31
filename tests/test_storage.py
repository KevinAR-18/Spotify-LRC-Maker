from pathlib import Path

from spotify_lrc_generator.lrc import LyricLine
from spotify_lrc_generator.storage import RecoveryStore, read_lrc_file, write_lrc_file


def test_atomic_write_and_read_lrc_file(tmp_path: Path) -> None:
    target = tmp_path / "song.lrc"

    write_lrc_file(target, [LyricLine("Line", 1234)])

    assert target.read_text(encoding="utf-8") == "[00:01.23]Line\n"
    assert [(line.text, line.timestamp_ms) for line in read_lrc_file(target)] == [("Line", 1230)]


def test_recovery_store_round_trip_and_clear(tmp_path: Path) -> None:
    store = RecoveryStore(tmp_path)
    source = tmp_path / "draft.lrc"
    lines = [LyricLine("One", 1000, "one")]

    store.save(lines, source, 0, -150)

    recovered = store.load()
    assert recovered is not None
    recovered_lines, recovered_path, index, offset = recovered
    assert [(line.text, line.timestamp_ms, line.line_id) for line in recovered_lines] == [("One", 1000, "one")]
    assert (recovered_path, index, offset) == (source, 0, -150)
    store.clear()
    assert store.load() is None
