"""Album art processing pipeline.

For each album produces:
  - 160x160 thumbnail  (album grid / cards)
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

THUMB_SIZE    = (160, 160)
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

    slug         = hashlib.md5(album_key.encode()).hexdigest()[:16]
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


# ── source acquisition ────────────────────────────────────────────────────────

def _get_source_image(audio_path: Path) -> Optional[Image.Image]:
    """Try embedded art, then sidecar files in the same folder."""
    data = extract_embedded_art(audio_path)
    if data:
        try:
            return Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            pass

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
    _crop_square(img).resize(THUMB_SIZE, Image.LANCZOS).save(path, "JPEG", quality=85)


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
