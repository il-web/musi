"""Audio tag reading via mutagen."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import mutagen

AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wav", ".opus"}


@dataclass
class TrackTags:
    path: Path
    title: str
    artist: str
    album: str
    album_artist: str
    track_number: Optional[int]
    disc_number: int
    year: Optional[int]
    duration: float
    has_embedded_art: bool


def is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTENSIONS


def read_tags(path: Path) -> Optional[TrackTags]:
    """Read metadata from an audio file. Returns None if unreadable."""
    try:
        audio = mutagen.File(path, easy=True)
    except Exception:
        return None

    if audio is None:
        return None

    title        = _first(audio, "title")        or path.stem
    artist       = _first(audio, "artist")        or "Unknown Artist"
    album        = _first(audio, "album")         or "Unknown Album"
    album_artist = _first(audio, "albumartist", "album_artist") or artist
    track_number = _parse_num(_first(audio, "tracknumber"))
    disc_number  = _parse_num(_first(audio, "discnumber")) or 1
    year         = _parse_year(_first(audio, "date", "year"))
    duration     = getattr(audio.info, "length", 0.0)

    return TrackTags(
        path=path,
        title=title,
        artist=artist,
        album=album,
        album_artist=album_artist,
        track_number=track_number,
        disc_number=disc_number,
        year=year,
        duration=duration,
        has_embedded_art=_has_embedded_art(path),
    )


# Fields the device API may edit → mutagen "easy" tag keys
WRITABLE_TAGS = {
    "title":        "title",
    "artist":       "artist",
    "album":        "album",
    "year":         "date",
    "track_number": "tracknumber",
}


def write_tags(path: Path, changes: dict) -> None:
    """Write a subset of WRITABLE_TAGS to the file. Raises on failure."""
    audio = mutagen.File(path, easy=True)
    if audio is None:
        raise ValueError("unsupported audio format")
    if audio.tags is None:
        audio.add_tags()
    for field, value in changes.items():
        audio[WRITABLE_TAGS[field]] = [str(value)]
    audio.save()


def extract_embedded_art(path: Path) -> Optional[bytes]:
    """Return raw image bytes from embedded album art, or None."""
    try:
        raw = mutagen.File(path)
        if raw is None:
            return None
        # ID3 (MP3)
        if hasattr(raw, "tags") and raw.tags:
            for key in raw.tags.keys():
                if key.startswith("APIC"):
                    return raw.tags[key].data
        # FLAC / OGG Vorbis
        if hasattr(raw, "pictures") and raw.pictures:
            return raw.pictures[0].data
        # MP4 / M4A
        if hasattr(raw, "tags") and raw.tags and "covr" in raw.tags:
            covers = raw.tags["covr"]
            if covers:
                return bytes(covers[0])
    except Exception:
        return None
    return None


# ── helpers ──────────────────────────────────────────────────────────────────

def _first(tag, *keys) -> str:
    for key in keys:
        val = tag.get(key)
        if val:
            v = val[0] if isinstance(val, list) else val
            s = str(v).strip()
            if s:
                return s
    return ""


def _parse_num(val: str) -> Optional[int]:
    """Parse '3' or '3/12' into 3."""
    if not val:
        return None
    try:
        return int(str(val).split("/")[0])
    except (ValueError, AttributeError):
        return None


def _parse_year(val: str) -> Optional[int]:
    if not val:
        return None
    try:
        return int(val[:4])
    except (ValueError, IndexError):
        return None


def _has_embedded_art(path: Path) -> bool:
    try:
        raw = mutagen.File(path)
        if raw is None:
            return False
        if hasattr(raw, "tags") and raw.tags:
            if any(k.startswith("APIC") for k in raw.tags.keys()):
                return True
        if hasattr(raw, "pictures") and raw.pictures:
            return True
        if hasattr(raw, "tags") and raw.tags and "covr" in raw.tags:
            return True
    except Exception:
        return False
    return False
