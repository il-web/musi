# musi — Component Measurements (for printable enclosure)

Source of truth: `components.xlsx`. Recorded values mirrored here for reference.
All units mm.

## Recorded

| # | Piece | L | W | H/Thick | Mount holes | Ports / edge | Notes |
|---|-------|---|---|---------|-------------|--------------|-------|
| 2 | Raspberry Pi Zero 2 W | 65 | 30 | 5 | 4 | none in use | standard board |
| 3 | Battery 606090 LiPo | 92 | 60 | 6 | 0 | — | incl. wrap |
| 4 | TP4056 charging module | 26 | 17 | ? | ? | USB-C on edge: ? | |
| 5 | PCM5102A DAC module | 31.9 | 16.9 | ? | ? | 3.5mm jack edge: ? | |
| 10 | MT3608 boost converter | 36 | 17 | **14** | ? | — | tallest component |

## Still needed (blocking the enclosure design)

1. **3.5" screen module (ST7796)** — CRITICAL, defines the whole front face:
   - outer PCB length × width × thickness
   - active (visible) area size and its offset from the PCB edges
   - any mounting holes
2. **Thicknesses**: TP4056, PCM5102A DAC (how tall they stand)
3. **Port edges**: which edge the TP4056 USB-C sits on; which edge the DAC 3.5mm jack sits on

## Not yet purchased (design cutouts parametrically, refine later)

- Direction buttons (×4), select button, power button — will use standard tactile
  footprints as placeholders so the holes are easy to adjust once chosen.

## No speaker.
