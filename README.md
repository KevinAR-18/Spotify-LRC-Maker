# Spotify LRC Maker

Spotify LRC Maker is a Windows desktop editor for creating and correcting line-synced `.lrc` lyric files while following Spotify Desktop playback. It reads the local Windows media session, so normal timestamping does not require Spotify credentials or a login flow.

## Requirements

- Windows 10 or Windows 11.
- Spotify Desktop for playback control and timestamp capture.
- Python 3.10 or newer.
- Internet access only when using the optional LRCLIB import.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Start Spotify Desktop and play a track before opening the timestamp screen. The app locks the current track on entry; if Spotify changes tracks, confirm the relock prompt before continuing to stamp.

## Main Workflow

1. Choose **New LRC**, open an existing file, drop an `.lrc` / `.txt` file onto the app, or optionally import from LRCLIB.
2. Edit lyric text. Existing matching lines preserve their timestamps.
3. Set an optional capture offset, then continue to timestamp mode.
4. Press `Space` to stamp the next unstamped line. Use per-line controls or **Shift all** to correct timing.
5. Run **Quality Check**, then save. Unstamped lines are intentionally omitted from the exported LRC after confirmation.

## Keyboard Shortcuts

| Shortcut | Action |
| --- | --- |
| `Space` | Stamp the next unstamped line in timestamp mode |
| `Ctrl+S` | Save |
| `Ctrl+Shift+S` | Save As |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `Ctrl+I` | Import from LRCLIB |
| `Ctrl+Shift+Q` | Quality Check |
| `F11` | Toggle fullscreen |

## LRCLIB

LRCLIB import is optional. The application sends only the current Spotify title and artist to the LRCLIB search endpoint when you explicitly request an import. Search results are shown in a picker; nothing replaces the current draft until you select a result and confirm. The app continues to work fully offline for manual editing and timestamping.

## Build

Use the included build script from a prepared virtual environment:

```bat
build.bat
```

The executable is created at `dist\Spotify LRC Maker.exe`.

## Development And Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest
```

GitHub Actions runs linting and tests on Windows with Python 3.10 and 3.12.

## License

MIT License. See [LICENSE](LICENSE).
