# musi OS · beta

A pocket-sized music player built on a Raspberry Pi Zero W — a 3.5" touchscreen,
a wired DAC or Bluetooth output, and an album-art-driven interface, all running
from a local library of your own files.

> **Status:** beta. It runs a real device end-to-end, but things are still moving.

## What it does

- **Plays your local library** (MP3 / FLAC / ALAC / OGG / …) via MPD — browse by
  artist → album → track, search, and a now-playing screen with album-art backdrop.
- **Touch-first UI** on a 320×480 ST7796 panel: swipe to scroll, drag to reorder the
  queue, tap transport controls, and a volume slider.
- **Audio anywhere:** wired **PCM5102A DAC** or a **Bluetooth** speaker/headphones,
  with automatic switching between them and on-device pairing.
- **Headphone media buttons** (play/pause/next/prev) via Bluetooth AVRCP.
- **Wi-Fi transfer** to drop new music onto the device from a browser.
- **Boots straight into the player** with a "musi" splash — no terminal needed.
- **Self-updates** over the air: **Settings → Updates → Update now** pulls the latest
  from this repo and restarts.

## Hardware

- Raspberry Pi Zero W
- 3.5" 320×480 ST7796 SPI display with FT5x06 capacitive touch
- PCM5102A I²S DAC
- LiPo battery + TP4056 (USB-C) charging, MT3608 boost
- 5-button cluster (D-pad + select) — touch covers transport

## Layout

- `src/musi/player/` — the touchscreen app (pygame), screens, MPD client, updater
- `src/musi/library/` — library scanner, album-art pipeline
- `src/musi/wifi_transfer/` — browser-based upload server
- `pi/` — deployment bits: systemd services, MPD config, Bluetooth/DAC audio router,
  Plymouth boot splash, initramfs hook
- `docs/` — design specs

## License

**PolyForm Noncommercial 1.0.0** — see [LICENSE.md](LICENSE.md).

You're free to use, modify, and share musi OS for **personal and noncommercial**
purposes (hobby, study, tinkering). **Commercial use requires a separate license** —
open an issue or contact the author ([il-web](https://github.com/il-web)) to arrange it.
