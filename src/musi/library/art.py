"""Album art processing pipeline.

For each album produces:
  - 320x320 thumbnail  (album grid / cards / Now Playing — the panel is 320
    wide, so this is full sharpness everywhere; it was 160 px until 2026-10)
  - 320x480 backdrop   (blurred, darkened — Now Playing background)
  - colour palette     (list of hex strings for UI accent colours)

Falls back to a deterministic gradient when no art is found.
"""

import hashlib
import io
import json
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter

from musi.library.tags import extract_embedded_art

THUMB_SIZE    = (320, 320)
OLD_THUMB     = (160, 160)
BACKDROP_SIZE = (320, 480)
PALETTE_N     = 4

SIDECAR_NAMES = [
    "cover.jpg", "cover.jpeg", "cover.png",
    "folder.jpg", "folder.jpeg", "folder.png",
    "album.jpg",  "album.jpeg",  "album.png",
    "front.jpg",  "front.jpeg",  "front.png",
]


def process_art(
    audio_path: Path,
    art_dir: Path,
    album_key: str,
) -> tuple[Optional[Path], Optional[Path], list[str]]:
    """Generate thumb + backdrop for an album and return their paths + palette.

    album_key is any stable string that uniquely identifies the album
    (e.g. "Artist::Album Title").
    """
    art_dir.mkdir(parents=True, exist_ok=True)

    slug         = album_slug(album_key)
    thumb_path   = art_dir / f"{slug}_thumb.jpg"
    backdrop_path = art_dir / f"{slug}_backdrop.jpg"
    palette_path = art_dir / f"{slug}_palette.json"

    # Already processed — load cached palette and return
    if thumb_path.exists() and backdrop_path.exists() and palette_path.exists():
        palette = json.loads(palette_path.read_text())
        return thumb_path, backdrop_path, palette

    # Acquire source image
    img = _get_source_image(audio_path)
    has_real_art = img is not None

    if not has_real_art:
        img = _make_gradient(album_key)

    palette = _extract_palette(img)
    _save_thumb(img, thumb_path)
    _save_backdrop(img, backdrop_path, blur=has_real_art)
    palette_path.write_text(json.dumps(palette))

    return thumb_path, backdrop_path, palette


def album_slug(album_key: str) -> str:
    """Stable cache-file prefix for an album key. Single source of truth."""
    return hashlib.md5(album_key.encode()).hexdigest()[:16]


def has_local_source(audio_path: Path) -> bool:
    """True if this track carries album art locally (embedded or a sidecar).

    Authoritative and retroactive: process_art writes a generated gradient when
    this is False, and the cache files it produces are indistinguishable from
    real art on disk, so the fetcher re-derives the answer here instead.
    """
    return _get_source_image(audio_path) is not None


def override_art(
    image_bytes: bytes,
    art_dir: Path,
    album_key: str,
) -> tuple[Path, Path, list[str]]:
    """Replace an album's cached art with a user-supplied image.

    Overwrites the slug-addressed cache files. A rescan treats existing cache
    files as authoritative (process_art returns them without re-extracting),
    so the override survives rescans — even if the album row is recreated.

    Raises on an unreadable image.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    art_dir.mkdir(parents=True, exist_ok=True)

    slug          = album_slug(album_key)
    thumb_path    = art_dir / f"{slug}_thumb.jpg"
    backdrop_path = art_dir / f"{slug}_backdrop.jpg"
    palette_path  = art_dir / f"{slug}_palette.json"

    palette = _extract_palette(img)
    _save_thumb(img, thumb_path)
    _save_backdrop(img, backdrop_path, blur=True)
    palette_path.write_text(json.dumps(palette))

    return thumb_path, backdrop_path, palette


# ── source acquisition ────────────────────────────────────────────────────────

def _get_source_image(audio_path: Path) -> Optional[Image.Image]:
    """Try embedded art, then sidecar files in the same folder."""
    data = extract_embedded_art(audio_path)
    if data:
        try:
            return Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            import logging
            logging.warning('Ignored exception', exc_info=True)

    for name in SIDECAR_NAMES:
        candidate = audio_path.parent / name
        if candidate.exists():
            try:
                return Image.open(candidate).convert("RGB")
            except Exception:
                continue

    return None


# ── image generation ──────────────────────────────────────────────────────────

def _save_thumb(img: Image.Image, path: Path) -> None:
    _crop_square(img).resize(THUMB_SIZE, Image.LANCZOS).save(path, "JPEG", quality=90)


def upgrade_thumb(audio_path: Path, art_dir: Path, album_key: str) -> bool:
    """Re-render an old small thumb at THUMB_SIZE from the album's own art.

    Only when the existing thumb is smaller AND it was made from this same
    source (an old-size render of the source matches it) — a cover the user
    or the fetcher put in place is left alone, and so is the generated
    gradient of an art-less album. True if the thumb was replaced.
    """
    thumb_path = art_dir / f"{album_slug(album_key)}_thumb.jpg"
    try:
        with Image.open(thumb_path) as cur:
            if cur.width >= THUMB_SIZE[0]:
                return False
            current = cur.convert("RGB")
    except Exception:
        return False
    src = _get_source_image(audio_path)
    if src is None:
        return False
    old = _crop_square(src).resize(current.size, Image.LANCZOS)
    from PIL import ImageChops, ImageStat
    diff = ImageStat.Stat(ImageChops.difference(old, current)).mean
    if sum(diff) / len(diff) > 12:          # not made from this art: keep it
        return False
    _save_thumb(src, thumb_path)
    return True


def _save_backdrop(img: Image.Image, path: Path, *, blur: bool) -> None:
    w, h = BACKDROP_SIZE
    ratio   = max(w / img.width, h / img.height)
    resized = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
    left    = (resized.width  - w) // 2
    top     = (resized.height - h) // 2
    cropped = resized.crop((left, top, left + w, top + h))

    if blur:
        cropped = cropped.filter(ImageFilter.GaussianBlur(radius=18))
        dark    = Image.new("RGB", cropped.size, (0, 0, 0))
        cropped = Image.blend(cropped, dark, 0.40)

    cropped.save(path, "JPEG", quality=80)


def _crop_square(img: Image.Image) -> Image.Image:
    w, h = img.size
    s = min(w, h)
    return img.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))


# ── palette extraction ────────────────────────────────────────────────────────

def _extract_palette(img: Image.Image) -> list[str]:
    """Return PALETTE_N dominant colours as hex strings."""
    small     = img.resize((64, 64), Image.LANCZOS)
    quantized = small.quantize(colors=PALETTE_N, method=Image.Quantize.MEDIANCUT)
    raw       = quantized.getpalette()[:PALETTE_N * 3]
    while len(raw) < PALETTE_N * 3:   # low-colour covers yield short palettes
        raw += raw[-3:]
    return [
        f"#{raw[i*3]:02x}{raw[i*3+1]:02x}{raw[i*3+2]:02x}"
        for i in range(PALETTE_N)
    ]


# ── gradient fallback ─────────────────────────────────────────────────────────

def _make_gradient(seed: str) -> Image.Image:
    """Deterministic vertical gradient derived from album_key hash."""
    h  = int(hashlib.md5(seed.encode()).hexdigest(), 16)

    def channel(shift: int) -> int:
        return max(60, (h >> shift) & 0xFF)

    r1, g1, b1 = channel(16), channel(8),  channel(0)
    r2, g2, b2 = channel(40), channel(32), channel(24)

    img  = Image.new("RGB", (320, 320))
    draw = ImageDraw.Draw(img)
    for y in range(320):
        t = y / 319
        draw.line(
            [(0, y), (320, y)],
            fill=(
                int(r1 + (r2 - r1) * t),
                int(g1 + (g2 - g1) * t),
                int(b1 + (b2 - b1) * t),
            ),
        )
    return img
