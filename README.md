# Spotify LRC Maker

Spotify LRC Maker is a Windows desktop app for creating and editing `.lrc` lyric files while syncing timestamps from Spotify Desktop playback.

The app is focused on manual, accurate line-level LRC creation. Paste lyrics, play a song in Spotify, and press the stamp button when the next lyric line starts. Spotify LRC Maker reads the current track position from the local Windows media session, so it does not require Spotify API credentials.

## Features

- Create a new LRC from plain pasted lyrics.
- Open and modify an existing `.lrc` file.
- Read Spotify Desktop metadata, playback status, duration, and progress from Windows media sessions.
- Control Spotify playback with play/pause, previous, next, row preview, and draggable progress seek.
- Stamp lyric timestamps using Spotify's current playback position.
- Adjust timestamps per line with small and large step controls.
- Click stamped lyric rows to preview playback from that timestamp.
- Export standard line-level LRC format: `[mm:ss.xx]lyric`.
- Custom dark UI with internal title bar, app icon, fullscreen toggle, and version label.

## Requirements

- Windows 10 or Windows 11.
- Spotify Desktop app.
- Python 3.10 or newer.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Start Spotify Desktop and play a song before entering the timestamp screen.

## Build

Use the included build script:

```bat
buildbat.bat
```

The script uses PyInstaller and outputs:

```text
dist\Spotify LRC Maker.exe
```

If PyInstaller is not installed in `.venv`, the script installs it automatically.

## Project Structure

```text
main.py
requirements.txt
buildbat.bat
icon.ico
images/
src/spotify_lrc_generator/
```

## Notes

- Spotify LRC Maker uses PyWinRT Windows media session packages instead of `winsdk`, avoiding local native wheel builds.
- No Spotify API key or login flow is required.
- Generated build outputs such as `dist/`, `build/`, `.spec`, `.exe`, cache folders, and `.txt` notes are ignored by Git.

## License

MIT License. See `LICENSE`.
