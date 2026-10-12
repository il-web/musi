"""The "sound rings" boot look — shared by the Plymouth splash and the app.

Power-on shows the Plymouth splash (pi/plymouth/musi.script); once the app
is up, its LoadingScreen takes over and keeps going: same wordmark, same
rings, same status line and progress bar, in the same pixels.

Both halves draw from one source. The text is not rendered at run time —
the dev PC and the Pi have different fonts — but shipped as images in
assets/boot/, made once by scripts/make_boot_splash.py with pygame's bundled
font. The rings are pygame.draw circles in both: the app draws them live,
the splash plays pre-drawn frames of the very same function.

Drawing is opaque on purpose: a ring's fade is its colour blended toward
the background, never an alpha layer (alpha blits crash the Pi's armv7 SDL
paths — see blit.py).
"""
from __future__ import annotations

from pathlib import Path

import pygame

from musi.player import theme

ASSETS = Path(__file__).parent / "assets" / "boot"

W, H = 320, 480
CX, CY = 160, 200            # rings + wordmark centre
R0, R1 = 52, 162             # ring radius: born → gone
PERIOD = 2.4                 # seconds for one ring to travel out
RINGS = 3                    # rings alive at once, evenly staggered
PEAK = 0.75                  # a fresh ring's strength over the background
STATUS_Y = 372               # status line centre
BAR = pygame.Rect(70, 392, 180, 4)
BAR_BG = (22, 22, 32)        # theme.CARD_BG
DIM = (120, 120, 135)        # theme.DIM

# The boot's status steps (image file, text). The splash shows the first;
# the app's LoadingScreen the rest, continuing the bar from APP_START.
STARTING = ("status-starting.png", "Starting services…")
CONNECTING = ("status-connecting.png", "Connecting to music…")
LOADING = ("status-loading.png", "Loading library…")
STEPS = (STARTING, CONNECTING, LOADING)
APP_START = 0.40

FRAMES = 30                  # splash ring frames per PERIOD
TICKS = 50                   # Plymouth calls its refresh ~50 times a second


def _mix(a: tuple, b: tuple, k: float) -> tuple:
    return tuple(int(round(x + (y - x) * k)) for x, y in zip(a, b))


def ring(phase: float) -> tuple[int, tuple, int]:
    """(radius, colour, width) of a ring ``phase`` (0..1) along its trip."""
    phase = phase % 1.0
    radius = int(round(R0 + phase * (R1 - R0)))
    colour = _mix(theme.BG, theme.ACCENT, (1 - phase) * PEAK)
    width = 2 if phase < 0.5 else 1
    return radius, colour, width


def phases(t: float) -> list[float]:
    """Phases of the live rings at ``t`` seconds, snapped to the splash's
    frames so the app's rings are exactly the splash's rings."""
    out = []
    for k in range(RINGS):
        ph = ((t / PERIOD) + k / RINGS) % 1.0
        out.append(int(ph * FRAMES) / FRAMES)
    return out


def draw_rings(surface: pygame.Surface, t: float) -> None:
    for ph in sorted(phases(t), reverse=True):     # faintest first
        r, col, w = ring(ph)
        pygame.draw.circle(surface, col, (CX, CY), r, w)


_images: dict[str, pygame.Surface | None] = {}


def image(name: str) -> pygame.Surface | None:
    if name not in _images:
        try:
            _images[name] = pygame.image.load(str(ASSETS / name))
        except (pygame.error, FileNotFoundError):
            _images[name] = None
    return _images[name]


def draw(surface: pygame.Surface, t: float, step: tuple[str, str] | str | None,
         progress: float | None) -> None:
    """One frame of the boot look. ``step`` is one of STEPS (drawn from its
    shipped image) or free text (e.g. an error); None hides it, as does
    ``progress`` None for the bar."""
    surface.fill(theme.BG)
    draw_rings(surface, t)
    word = image("wordmark.png")
    if word is None:
        word = theme.render("musi", 48, theme.WHITE, bold=True)
    surface.blit(word, word.get_rect(center=(CX, CY)))
    if step:
        s = image(step[0]) if isinstance(step, tuple) else None
        if s is None:
            text = step[1] if isinstance(step, tuple) else step
            s = theme.render(text, 13, DIM, max_width=290)
        surface.blit(s, s.get_rect(center=(CX, STATUS_Y)))
    if progress is not None:
        pygame.draw.rect(surface, BAR_BG, BAR, border_radius=2)
        fill = BAR.copy()
        fill.width = max(BAR.height, int(BAR.width * max(0.0, min(1.0, progress))))
        pygame.draw.rect(surface, theme.ACCENT, fill, border_radius=2)


# ── making the shipped images + the splash script ────────────────────────────

def _text(text: str, px: int, colour: tuple) -> pygame.Surface:
    """Text on real transparency, in pygame's bundled font (same everywhere)."""
    rendered = pygame.font.Font(None, px).render(text, True, colour)
    s = pygame.Surface(rendered.get_size(), pygame.SRCALPHA)
    s.fill((0, 0, 0, 0))
    s.blit(rendered, (0, 0))
    return s


def make_assets(out: Path = ASSETS) -> list[Path]:
    """Render every boot image into ``out``; returns the files written.

    ring-NN.png  one ring at phase NN/FRAMES on transparency, screen-sized so
                 every frame sits at (0, 0) — no per-frame maths in the script
    wordmark.png, status-*.png, bar-bg.png, bar-fg.png
    """
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def save(surf: pygame.Surface, name: str) -> None:
        p = out / name
        pygame.image.save(surf, str(p))
        written.append(p)

    for i in range(FRAMES):
        s = pygame.Surface((W, H), pygame.SRCALPHA)
        s.fill((0, 0, 0, 0))
        r, col, w = ring(i / FRAMES)
        pygame.draw.circle(s, (*col, 255), (CX, CY), r, w)
        save(s, f"ring-{i:02d}.png")

    save(_text("musi", 66, theme.WHITE), "wordmark.png")
    for name, text in STEPS:
        save(_text(text, 20, DIM), name)
    for name, col in (("bar-bg.png", BAR_BG), ("bar-fg.png", theme.ACCENT)):
        s = pygame.Surface(BAR.size, pygame.SRCALPHA)
        s.fill((0, 0, 0, 0))
        pygame.draw.rect(s, (*col, 255), s.get_rect(), border_radius=2)
        save(s, name)
    return written


def splash_script() -> str:
    """The Plymouth script, with this module's geometry baked in."""
    word = pygame.image.load(str(ASSETS / "wordmark.png")).get_size()
    st = pygame.image.load(str(ASSETS / STARTING[0])).get_size()
    v = {
        "BG": "%.3f, %.3f, %.3f" % tuple(c / 255 for c in theme.BG),
        "W": W, "H": H, "FRAMES": FRAMES, "RINGS": RINGS,
        "TICKS_PER_PERIOD": int(round(PERIOD * TICKS)),
        "WORD_X": CX - word[0] // 2, "WORD_Y": CY - word[1] // 2,
        "STATUS_X": CX - st[0] // 2, "STATUS_Y": STATUS_Y - st[1] // 2,
        "BAR_X": BAR.x, "BAR_Y": BAR.y, "BAR_W": BAR.width, "BAR_H": BAR.height,
        "APP_START": APP_START,
    }
    return _SCRIPT.format(**v)


_SCRIPT = """\
# musi boot splash — "sound rings". GENERATED by scripts/make_boot_splash.py
# from src/musi/player/boot_look.py; edit those, not this file. The app's
# loading screen draws the same look and takes over where this leaves off.

Window.SetBackgroundTopColor({BG});
Window.SetBackgroundBottomColor({BG});

# The design is 320x480 (the panel); centre it if the screen differs.
ox = Math.Int((Window.GetWidth() - {W}) / 2);
oy = Math.Int((Window.GetHeight() - {H}) / 2);

for (i = 0; i < {FRAMES}; i++) {{
    if (i < 10) {{ frame[i] = Image("ring-0" + i + ".png"); }}
    else {{ frame[i] = Image("ring-" + i + ".png"); }}
}}
for (k = 0; k < {RINGS}; k++) {{
    ring[k] = Sprite(frame[0]);
    ring[k].SetPosition(ox, oy, 1 + k);
}}

word = Sprite(Image("wordmark.png"));
word.SetPosition(ox + {WORD_X}, oy + {WORD_Y}, 10);
status = Sprite(Image("status-starting.png"));
status.SetPosition(ox + {STATUS_X}, oy + {STATUS_Y}, 10);
bar_bg = Sprite(Image("bar-bg.png"));
bar_bg.SetPosition(ox + {BAR_X}, oy + {BAR_Y}, 10);
bar_img = Image("bar-fg.png");
bar = Sprite(bar_img.Scale({BAR_H}, {BAR_H}));
bar.SetPosition(ox + {BAR_X}, oy + {BAR_Y}, 11);
shown = 0;

t = 0;
fun refresh() {{
    t++;
    for (k = 0; k < {RINGS}; k++) {{
        x = t / {TICKS_PER_PERIOD} + k / {RINGS};
        ph = x - Math.Int(x);
        f = Math.Int(ph * {FRAMES});
        # fresher rings in front: z follows the phase, smallest on top
        ring[k].SetImage(frame[f]);
        ring[k].SetZ(1 + {FRAMES} - f);
    }}
}}
Plymouth.SetRefreshFunction(refresh);

# Boot progress fills the first part of the bar; the app does the rest.
fun progress(duration, p) {{
    w = Math.Int({BAR_W} * {APP_START} * p);
    if (w < {BAR_H}) {{ w = {BAR_H}; }}
    if (w != shown) {{
        shown = w;
        bar.SetImage(bar_img.Scale(w, {BAR_H}));
    }}
}}
Plymouth.SetBootProgressFunction(progress);

# No boot messages, no password prompts drawn over the art.
fun message(text) {{ }}
Plymouth.SetMessageFunction(message);
"""
