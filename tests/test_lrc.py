from spotify_lrc_generator.lrc import (
    LyricLine,
    export_lrc,
    merge_editor_lines,
    parse_lrc,
    shift_timestamp,
    validate_lines,
)


def test_parse_and_export_lrc_round_trip() -> None:
    lines = parse_lrc("[00:01.2]First\n[01:02.345]Second\n")

    assert [(line.text, line.timestamp_ms) for line in lines] == [("First", 1200), ("Second", 62345)]
    assert export_lrc(lines) == "[00:01.20]First\n[01:02.35]Second\n"


def test_merge_editor_lines_keeps_matching_line_identity_and_timestamp() -> None:
    original = [LyricLine("First", 1000, "first"), LyricLine("Second", 2000, "second")]

    merged = merge_editor_lines(original, "New intro\nFirst\nSecond\n")

    assert [(line.text, line.timestamp_ms, line.line_id) for line in merged] == [
        ("New intro", None, merged[0].line_id),
        ("First", 1000, "first"),
        ("Second", 2000, "second"),
    ]


def test_adjusting_an_unstamped_line_does_not_create_timestamp() -> None:
    assert shift_timestamp(None, 100) is None


def test_validation_reports_unstamped_duplicate_and_out_of_order_lines() -> None:
    issues = validate_lines(
        [LyricLine("One", 1000), LyricLine("Two", 1000), LyricLine("Three", 900), LyricLine("Four")],
        duration_ms=950,
    )

    messages = [issue.message for issue in issues]
    assert "Timestamp duplicates the previous line." in messages
    assert "Timestamp is earlier than the previous line." in messages
    assert "Line has no timestamp and will be skipped." in messages
    assert messages.count("Timestamp is beyond the current track duration.") == 2
