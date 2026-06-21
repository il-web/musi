# musi OS · beta

A tiny, touch-first music player operating system for the Raspberry Pi. Flash a
Pi, wire up a small SPI screen and a DAC (or just use Bluetooth), and you get a
self-contained pocket music player: album-art UI, your own local library, wired
**and** Bluetooth audio with automatic switching, on-device pairing, a boot
splash, and over-the-air updates.

> **Status: beta.** It runs a real device end-to-end, but it targets a specific
> class of hardware and setup still involves wiring and a few config edits.

---

## What it does

- **Plays your local library** (MP3 / FLAC / ALAC / OGG / …) through MPD — browse
  artist → album → track, full-text search, now-playing with album-art backdrop.
- **Touch-first UI** on a 320×480 panel: swipe to scroll, drag to reorder the
  queue, transport controls, volume slider.
- **Audio anywhere:** wired I²S **DAC** and/or **Bluetooth** A2DP, with automatic
  switching and on-device scan/pair/connect.
- **Headphone media buttons** (play/pause/next/prev) via Bluetooth AVRCP.
- **Wi-Fi transfer:** drop new music onto the device from any browser.
- **Appliance boot:** powers straight into the player with a "musi" splash — no
  terminal, no login.
- **Over-the-air updates:** Settings → Updates → *Update now* pulls the latest and
  restarts.

---

## Hardware requirements

musi OS targets a Raspberry Pi with a small **SPI display** and an **I²S DAC**
and/or Bluetooth. The UI is fixed at **320×480 portrait**.

| Part | Requirement | Notes |
|------|-------------|-------|
| **Board** | Any Raspberry Pi with the 40-pin header | **Pi Zero 2 W recommended** (quad-core). Pi Zero W works but is tight (single-core ARMv6). |
| **RAM** | 512 MB minimum | The whole stack fits in 512 MB. |
| **Display** | 3.5" **320×480 SPI**, **ST7796** controller | Driven by the kernel `panel-mipi-dbi` (MIPI-DBI) driver. ILI9488 may work with a different init sequence. |
| **Touch** | **FT5x06 / FT6236** capacitive over I²C | Driver `edt-ft5x06`. Other I²C controllers (e.g. Goodix GT911) need a different overlay. |
| **Audio (wired)** | **PCM5102A** I²S DAC | Optional if you only use Bluetooth. |
| **Audio (wireless)** | Onboard Bluetooth (A2DP) | Built into Pi Zero W / Zero 2 W. |
| **Storage** | microSD 8 GB+ | Plus room for your music. |
| **Power** | 5 V | Battery optional: LiPo + TP4056 (USB-C charge) + MT3608 boost. |
| **OS** | Raspberry Pi OS (Bookworm/Trixie) | 32-bit on ARMv6 boards. |

> The display and touch controllers are the parts most likely to differ between
> vendors. If yours uses a different controller, you'll need a matching init
> sequence (display) or device-tree overlay (touch) — see `docs/` and `pi/`.

### Tested configuration

This is the exact hardware musi OS has been run and verified on:

- **Raspberry Pi Zero W** (2017, BCM2835, single-core ARMv6, 512 MB)
- **3.5" 320×480 ST7796** SPI display, **FT5x06** capacitive touch (I²C `0x38`)
- **PCM5102A** I²S DAC
- Bluetooth: a generic A2DP speaker and A2DP headphones
- **Raspberry Pi OS (Trixie / Debian 13), 32-bit**

Other boards/panels in the same class are expected to work but haven't been
verified yet — reports welcome.

---

## Installation

### 1. Flash the OS

Flash **Raspberry Pi OS Lite** (32-bit on a Pi Zero/Zero 2) to a microSD. Enable
SSH and Wi-Fi in Raspberry Pi Imager so you can reach the board headless.

### 2. Wire the display, touch, and DAC

Connect the panel (SPI), the touch controller (I²C), and the DAC (I²S) to the
40-pin header. Key points for the tested hardware: the DAC's **`SCK` must be tied
to `GND`** (the Pi has no master clock), and the ST7796 panel needs a compiled
**`panel.bin`** init blob. A full wiring guide is in progress — see
[`docs/`](docs/) and the deployment files in [`pi/`](pi/).

### 3. Enable the hardware in `config.txt`

Add to `/boot/firmware/config.txt` (disable onboard audio, enable SPI/I²C/I²S and
the display + DAC overlays):

```ini
dtparam=spi=on
dtparam=i2c_arm=on
dtparam=i2s=on
#dtparam=audio=on
dtoverlay=hifiberry-dac
dtoverlay=mipi-dbi-spi,spi0-0,speed=40000000
dtparam=width=320,height=480,reset-gpio=25,dc-gpio=24,backlight-gpio=12,write-only
```

The ST7796 panel needs a compiled init blob at `/lib/firmware/panel.bin` (built
with [`mipi-dbi-cmd`](https://github.com/notro/panel-mipi-dbi)) and the touch
controller needs an I²C overlay — both are covered in `pi/` and `docs/`.

### 4. Install musi OS

On the Pi:

```bash
git clone https://github.com/il-web/musi.git ~/musi
cd ~/musi
bash install.sh
```

The installer sets up MPD, the Python app, the audio routing (DAC + Bluetooth via
bluez-alsa), the Bluetooth pairing agent, AVRCP control, the boot splash, and the
auto-start service.

### 5. Reboot

```bash
sudo reboot
```

The Pi boots into musi OS. Put music in `~/music` (or use **Wi-Fi transfer**),
and you're playing.

> The hardware/`config.txt` steps are manual because they depend on your exact
> panel and wiring — the software side (step 4) is scripted.

---

## Updating

On the device: **Settings → Updates → Update now**. It pulls the latest from this
repo and restarts. (Under the hood it's a `git pull` of `~/musi`.)

---

## Repository layout

- `src/musi/player/` — the touchscreen app (pygame): screens, MPD client, updater
- `src/musi/library/` — library scanner and album-art pipeline
- `src/musi/wifi_transfer/` — browser-based upload server
- `pi/` — deployment: systemd services, MPD config, Bluetooth/DAC audio router,
  Bluetooth agent, Plymouth boot splash, initramfs hook
- `docs/` — design specs and hardware notes

---

## License

**PolyForm Noncommercial 1.0.0** — see [LICENSE.md](LICENSE.md).

Free to use, modify, and share for **personal and noncommercial** purposes
(hobby, study, tinkering). **Commercial use requires a separate license** — open an
issue or contact [il-web](https://github.com/il-web) to arrange it.
