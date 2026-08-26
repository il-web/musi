# musi OS · beta

A tiny, touch-first music player operating system for the Raspberry Pi. Point it
at a small screen and an audio output and you get a self-contained pocket music
player: album-art UI, your own local library, wired **and** Bluetooth audio with
automatic switching, on-device pairing, a boot splash, and over-the-air updates.

> **Status: beta.** Runs a real device end-to-end. The clean-install path is new —
> reports welcome.

---

## What it does

- **Plays your local library** (MP3 / FLAC / ALAC / OGG / …) through MPD — browse
  artist → album → track, full-text search, now-playing with album-art backdrop.
- **Touch-first UI** at 320×480: swipe to scroll, drag to reorder the queue,
  transport controls, volume slider.
- **Audio anywhere:** wired I²S **DAC** and/or **Bluetooth** A2DP, with automatic
  switching and on-device scan/pair/connect.
- **Headphone media buttons** (play/pause/next/prev) via Bluetooth AVRCP.
- **Wi-Fi transfer:** drop new music onto the device from any browser.
- **Appliance boot:** powers straight into the player with a splash — no terminal.
- **Over-the-air updates:** Settings → Updates → *Update now*.

---

## Requirements

musi OS runs on top of a working Raspberry Pi OS install. It uses whatever the OS
already exposes — it does **not** drive your panel or sound card itself.

- **Board:** any Raspberry Pi with the 40-pin header. A **Pi 3 or Pi Zero 2 W** gives
  the UI comfortable headroom (a single-core Pi Zero W works, but it is tight).
- **RAM:** 512 MB or more.
- **Display:** anything Linux can render to at **320×480 portrait** — an SPI TFT,
  DSI, or HDMI screen. The UI is fixed at this resolution.
- **Touch:** a touch input device (evdev). Optional, but the UI is touch-first.
- **Audio:** an I²S DAC and/or onboard Bluetooth (A2DP).
- **Storage:** microSD 8 GB+, plus room for your music.
- **OS:** Raspberry Pi OS (Bookworm / Trixie).

> **You bring the hardware working in Linux; musi OS provides the player.**
> Getting your specific display, touch panel, and DAC running — wiring, device-tree
> overlays, drivers — depends entirely on your parts and is done **before**
> installing musi OS. The installer assumes a 320×480 framebuffer/DRM display, a
> touch evdev (optional), and an ALSA output are already present.

### Tested configuration

One known-good setup, for reference:

- **Raspberry Pi 3 Model B** (BCM2837, quad-core ARMv8, 1 GB) — the current build.
  A **Pi Zero W** (single-core ARMv6, 512 MB) also ran this setup, just with no headroom.
- 3.5" **320×480 ST7796** SPI display, **FT5x06** capacitive touch
- **PCM5102A** I²S DAC (`dtparam=i2s=on` + `dtoverlay=hifiberry-dac`), plus Bluetooth
  A2DP speaker/headphones
- **Raspberry Pi OS (Trixie / Debian 13)** — tested 32-bit on the Zero W

> On a board with HDMI audio present, the ALSA card index is not stable across boots.
> musi looks the DAC up by card **name**, not index — see `pi/musi-bt-router`.

---

## Install

**1.** Flash **Raspberry Pi OS Lite** and enable SSH + Wi-Fi (Raspberry Pi Imager).

**2.** Get your **display, touch, and audio working in Linux first** — your
hardware, your method. Sanity checks:

```bash
ls /dev/fb* /dev/dri/card*     # your screen shows up as a framebuffer / DRM card
sudo apt install -y evtest && sudo evtest   # touching produces events (optional)
aplay -l                        # your DAC is listed  (or pair a Bluetooth device)
```

**3.** Install musi OS:

```bash
git clone https://github.com/il-web/musi.git ~/musi
cd ~/musi
bash install.sh
```

The installer sets up MPD, the player app, audio routing (DAC + Bluetooth via
bluez-alsa) with automatic switching, the Bluetooth pairing agent and AVRCP, an
optional boot splash, and the auto-start service.

**4.** Reboot:

```bash
sudo reboot
```

The Pi boots straight into musi OS. Add music to `~/music` (or use **Wi-Fi
transfer**) and play.

---

## Updating

On the device: **Settings → Updates → Update now** — pulls the latest from this
repo and restarts.

---

## Repository layout

- `src/musi/player/` — the touchscreen app (pygame): screens, MPD client, updater
- `src/musi/library/` — library scanner and album-art pipeline
- `src/musi/wifi_transfer/` — browser-based upload server
- `pi/` — services, MPD config, Bluetooth/DAC audio router, pairing agent,
  optional boot splash

---

## License

**PolyForm Noncommercial 1.0.0** — see [LICENSE.md](LICENSE.md).

Free to use, modify, and share for **personal and noncommercial** purposes.
**Commercial use requires a separate license** — open an issue or contact
[il-web](https://github.com/il-web).
