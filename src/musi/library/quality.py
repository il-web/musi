"""Audio quality — what format a track is in, and the album page's tags.

Per track the library stores codec, bitrate (kbps), sample rate (Hz), bit
depth and channels: read from the file by ``probe`` (scanner) or from the
music server's song entry by ``from_subsonic`` (subsonic_sync).

``badges`` turns an album's tracks into the tags shown under its title:
the format (FLAC, MP3, Dolby Digital…), then the quality (Hi-Res 24-bit /
96 kHz, Lossless, 320 kbps) and surround channels (5.1, 7.1).

Dolby Atmos rides inside Dolby Digital Plus / TrueHD and isn't flagged in a
way mutagen can read, so an E-AC-3 / TrueHD album is called Atmos when its
name, a title or a file name says so.
"""
from __future__ import annotations

from pathlib import Path

LOSSLESS = {"FLAC", "ALAC", "WAV", "AIFF", "APE", "WavPack", "DSD", "TrueHD"}
DOLBY = {"AC-3": "Dolby Digital", "E-AC-3": "Dolby Digital Plus",
         "TrueHD": "Dolby TrueHD"}
FIELDS = ("codec", "bitrate", "sample_rate", "bit_depth", "channels")


def _mp4_codec(codec: str) -> str:
    c = (codec or "").lower()
    if c.startswith("alac"):
        return "ALAC"
    if c.startswith("ec-3"):
        return "E-AC-3"
    if c.startswith("ac-3"):
        return "AC-3"
    if c.startswith("mp4a"):
        return "AAC"
    return c.upper() or "AAC"


def probe(path: Path) -> dict:
    """Format details of an audio file; empty dict if mutagen can't tell."""
    try:
        import mutagen
        f = mutagen.File(path)
    except Exception:
        return {}
    if f is None or getattr(f, "info", None) is None:
        return {}
    info = f.info
    kind = type(f).__name__
    codec = {
        "FLAC": "FLAC", "MP3": "MP3", "EasyMP3": "MP3",
        "OggVorbis": "Vorbis", "OggOpus": "Opus", "OggFLAC": "FLAC",
        "WAVE": "WAV", "AIFF": "AIFF", "DSF": "DSD", "DSDIFF": "DSD",
        "WavPack": "WavPack", "MonkeysAudio": "APE", "AAC": "AAC",
    }.get(kind)
    if kind in ("MP4", "EasyMP4"):
        codec = _mp4_codec(getattr(info, "codec", ""))
    elif kind == "AC3":
        codec = "E-AC-3" if str(getattr(info, "codec", "")).lower() == "ec-3" else "AC-3"
    if not codec:
        codec = Path(path).suffix.lstrip(".").upper() or None
    bitrate = getattr(info, "bitrate", 0) or 0
    return {
        "codec": codec,
        "bitrate": int(round(bitrate / 1000)) if bitrate else None,
        "sample_rate": getattr(info, "sample_rate", None) or None,
        "bit_depth": (getattr(info, "bits_per_sample", None)
                      or getattr(info, "bits_per_raw_sample", None) or None),
        "channels": getattr(info, "channels", None) or None,
    }


_SUFFIX = {"flac": "FLAC", "mp3": "MP3", "ogg": "Vorbis", "oga": "Vorbis",
           "opus": "Opus", "wav": "WAV", "aif": "AIFF", "aiff": "AIFF",
           "dsf": "DSD", "dff": "DSD", "wv": "WavPack", "ape": "APE",
           "aac": "AAC", "ac3": "AC-3", "eac3": "E-AC-3", "ec3": "E-AC-3",
           "thd": "TrueHD", "mlp": "TrueHD"}


def from_subsonic(song: dict) -> dict:
    """The same fields from a Subsonic / OpenSubsonic song entry."""
    suffix = str(song.get("suffix") or "").lower()
    codec = _SUFFIX.get(suffix)
    bit_depth = song.get("bitDepth") or None
    bitrate = song.get("bitRate") or None
    if codec is None and suffix in ("m4a", "mp4", "m4b", "alac"):
        # m4a holds AAC or ALAC; a bit depth or a lossless-sized bitrate is ALAC
        codec = "ALAC" if (suffix == "alac" or bit_depth or (bitrate or 0) > 500) else "AAC"
    if codec is None and suffix:
        codec = suffix.upper()
    return {"codec": codec, "bitrate": bitrate,
            "sample_rate": song.get("samplingRate") or None,
            "bit_depth": bit_depth,
            "channels": song.get("channelCount") or None}


# ── album tags ────────────────────────────────────────────────────────────────

def _khz(rate: int) -> str:
    k = rate / 1000
    return f"{k:g} kHz" if k != int(k) else f"{int(k)} kHz"


def _format_label(codec: str, atmos: bool) -> str:
    if codec in DOLBY:
        return "Dolby Atmos" if atmos and codec in ("E-AC-3", "TrueHD") else DOLBY[codec]
    return codec


def badges(tracks: list[dict], album_title: str = "") -> list[tuple[str, str]]:
    """[(label, kind)] for an album. kind: "format" | "hires" | "lossless" |
    "lossy" | "dolby" | "surround" — the album page colours by it."""
    known = [t for t in tracks if t.get("codec")]
    if not known:
        return []
    names = " ".join([album_title] + [str(t.get("title") or "") + " " + str(t.get("path") or "")
                                      for t in known]).lower()
    atmos = "atmos" in names

    # formats, most common first (an album is usually one)
    counts: dict[str, int] = {}
    for t in known:
        counts[t["codec"]] = counts.get(t["codec"], 0) + 1
    codecs = sorted(counts, key=lambda c: -counts[c])
    out: list[tuple[str, str]] = []
    for c in codecs[:2]:
        out.append((_format_label(c, atmos), "dolby" if c in DOLBY else "format"))

    main = codecs[0]
    mains = [t for t in known if t["codec"] == main]
    depth = max((t.get("bit_depth") or 0) for t in mains)
    rate = max((t.get("sample_rate") or 0) for t in mains)
    if main in LOSSLESS and main != "TrueHD":
        if main == "DSD":
            out.append((f"DSD{rate // 44100}" if rate >= 2822400 else "DSD", "hires"))
        elif depth >= 24 or rate > 48000:
            detail = " / ".join(x for x in (f"{depth}-bit" if depth else "",
                                            _khz(rate) if rate else "") if x)
            out.append((f"Hi-Res {detail}".strip(), "hires"))
        else:
            detail = " / ".join(x for x in (f"{depth}-bit" if depth else "",
                                            _khz(rate) if rate else "") if x)
            out.append((f"Lossless {detail}".strip(), "lossless"))
    elif main not in DOLBY:
        rates = sorted(t.get("bitrate") or 0 for t in mains)
        typical = rates[len(rates) // 2]
        if typical:
            out.append((f"{typical} kbps", "lossy"))

    ch = max((t.get("channels") or 0) for t in known)
    if ch >= 8:
        out.append(("7.1", "surround"))
    elif ch >= 6:
        out.append(("5.1", "surround"))
    return out
