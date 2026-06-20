# musi — 3D Enclosure Model (Visual Concept)

**Design doc — v1**
**Date:** 2026-06-06
**Tool:** OpenSCAD (`3D model/musi.scad`)

## Purpose

A parametric, good-looking **visual concept** render of the finished musi player —
to evaluate proportions and style before committing to a real, printable enclosure.

Out of scope for this version: wall thickness/hollowing, screw bosses, snap-fits,
print tolerances, and internal component models (battery/PCB/Pi). Those come in the
"real" printable revision if the look is approved.

## Hardware being represented (current revision)

- Raspberry Pi Zero 2 W
- 3.5" SPI touchscreen, **320×480** (ST7796), active area ≈ 49 × 74 mm
- **5 buttons in a circular cluster**: up / down / left / right on a ring + center select
- **1 power button**
- **USB-C** charging port
- 606090 LiPo battery (≈ 6 mm thick) — informs body thickness only

## Form decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Front-face layout | **Screen-maximal** — screen ≈ 72% of face, compact button ring below |
| Body shape | **Chunky, flat sides, crisp square corners** (~1.5 mm edge break) |
| Power button | **Top edge**, toward the right |
| USB-C port | **Bottom edge**, centered |
| Approx size | **70 mm W × 120 mm H × 19 mm D** |
| Default color | Space-gray body, near-black screen glass, light-gray buttons |

## Code structure (single `musi.scad`)

1. **Parameters block** — all dimensions and the color palette as named variables at the
   top. Change one number → whole model updates.
2. **Modules** — `body_shell()`, `screen_panel()`, `dpad_cluster()`, `power_button()`,
   `usbc_port()`.
3. **`musi()` assembly** — composes the modules with `color()` for clear preview.
4. Front face oriented **+Z up** so OpenSCAD's default view (F5) shows the front.

## Front-face layout details

- **Screen glass:** ≈ 60 × 82 mm near-black panel in the upper face, with the
  49 × 74 mm active display area faintly shown inset within it.
- **Button ring:** ≈ 34 mm outer diameter, centered horizontally, in the lower face.
  Ring carries ▲▼◀▶ direction marks; a recessed round **select** button in the center.

## Next steps (deferred)

If the look is approved, continue to the **real** printable model: hollow shell,
two-part split, component mounts, accurate cutout tolerances, and fastening.
