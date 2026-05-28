from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Any

MEDIA_TIMEOUT_SECONDS = 2.5


class MediaSessionError(RuntimeError):
    pass


@dataclass
class MediaState:
    available: bool
    app_id: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    playback_status: str = "Unavailable"
    position_ms: int | None = None
    duration_ms: int | None = None
    sampled_at: float = 0.0
    message: str = ""


def get_media_state() -> MediaState:
    return asyncio.run(_with_timeout(_get_media_state()))


def play_pause() -> bool:
    return asyncio.run(_with_timeout(_play_pause(), fallback=False))


def next_track() -> bool:
    return asyncio.run(_with_timeout(_command("try_skip_next_async"), fallback=False))


def previous_track() -> bool:
    return asyncio.run(_with_timeout(_command("try_skip_previous_async"), fallback=False))


def seek_to(position_ms: int) -> bool:
    return asyncio.run(_with_timeout(_seek_to(position_ms), fallback=False))


def play_from(position_ms: int) -> bool:
    return asyncio.run(_with_timeout(_play_from(position_ms), fallback=False))


async def _with_timeout(coro, fallback=None):
    try:
        return await asyncio.wait_for(coro, timeout=MEDIA_TIMEOUT_SECONDS)
    except TimeoutError:
        if fallback is not None:
            return fallback
        return MediaState(False, message="Timed out while connecting to Spotify media session.")


async def _get_media_state() -> MediaState:
    try:
        session = await _get_spotify_session()
        if session is None:
            return MediaState(False, message="Spotify media session not found.")

        timeline = session.get_timeline_properties()
        playback = session.get_playback_info()
        media = await session.try_get_media_properties_async()

        is_playing = _is_playing(playback)
        sampled_at = monotonic()
        position_ms = _timeline_position_ms(
            getattr(timeline, "position", None),
            getattr(timeline, "last_updated_time", None),
            advance=is_playing,
        )
        duration_ms = max(
            _timespan_to_ms(getattr(timeline, "end_time", None) or 0)
            - _timespan_to_ms(getattr(timeline, "start_time", None) or 0),
            0,
        )

        return MediaState(
            available=True,
            app_id=_safe_call(session, "source_app_user_model_id") or "",
            title=getattr(media, "title", "") or "",
            artist=getattr(media, "artist", "") or "",
            album=getattr(media, "album_title", "") or "",
            playback_status=_playback_status_name(getattr(playback, "playback_status", None)),
            position_ms=min(position_ms, duration_ms) if duration_ms > 0 else position_ms,
            duration_ms=duration_ms,
            sampled_at=sampled_at,
        )
    except ImportError as exc:
        return MediaState(
            False,
            message=(
                "Windows media session dependency is incomplete. Run "
                "`pip install -r requirements.txt`. Details: "
                f"{exc}"
            ),
        )
    except Exception as exc:
        return MediaState(False, message=f"Unable to read media session: {exc}")


async def _play_pause() -> bool:
    session = await _get_spotify_session()
    if session is None:
        return False

    playback = session.get_playback_info()
    status = _playback_status_name(getattr(playback, "playback_status", None)).lower()
    if status == "playing":
        return bool(await session.try_pause_async())
    return bool(await session.try_play_async())


async def _command(method_name: str) -> bool:
    session = await _get_spotify_session()
    if session is None:
        return False
    method = getattr(session, method_name)
    return bool(await method())


async def _seek_to(position_ms: int) -> bool:
    session = await _get_spotify_session()
    if session is None:
        return False
    method = getattr(session, "try_change_playback_position_async", None)
    if method is None:
        return False
    return bool(await method(max(0, position_ms) * 10_000))


async def _play_from(position_ms: int) -> bool:
    session = await _get_spotify_session()
    if session is None:
        return False

    seek_method = getattr(session, "try_change_playback_position_async", None)
    seek_ok = True
    if seek_method is not None:
        seek_ok = bool(await seek_method(max(0, position_ms) * 10_000))
    play_ok = bool(await session.try_play_async())
    return seek_ok and play_ok


async def _get_spotify_session() -> Any | None:
    try:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
    except ImportError as winrt_exc:
        raise ImportError(f"PyWinRT media control unavailable ({winrt_exc})") from winrt_exc

    manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
    current = manager.get_current_session()
    if current and "spotify" in ((_safe_call(current, "source_app_user_model_id") or "").lower()):
        return current

    for session in manager.get_sessions():
        if "spotify" in ((_safe_call(session, "source_app_user_model_id") or "").lower()):
            return session
    return None


def _safe_call(obj: Any, name: str) -> Any:
    value = getattr(obj, name, None)
    if callable(value):
        return value()
    return value


def _timespan_to_ms(value: Any) -> int:
    if value is None:
        return 0
    if hasattr(value, "total_seconds"):
        return max(int(value.total_seconds() * 1000), 0)
    if isinstance(value, int):
        return max(int(value / 10_000), 0)
    return 0


def _timeline_position_ms(position: Any, last_updated_time: datetime | None, advance: bool) -> int:
    progress_ms = _timespan_to_ms(position)
    if not advance or last_updated_time is None:
        return progress_ms

    updated_utc = last_updated_time.astimezone(timezone.utc)
    elapsed_ms = int((datetime.now(timezone.utc) - updated_utc).total_seconds() * 1000)
    return progress_ms + max(elapsed_ms, 0)


def _is_playing(playback: Any) -> bool:
    return _playback_status_name(getattr(playback, "playback_status", None)).lower() == "playing"


def _playback_status_name(value: Any) -> str:
    if value is None:
        return "Unknown"
    name = getattr(value, "name", None)
    if name:
        return str(name).title()
    text = str(value)
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.replace("_", " ").title()
