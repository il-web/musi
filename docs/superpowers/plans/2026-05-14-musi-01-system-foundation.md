# musi 01 — System Foundation & Hello World Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring up a Raspberry Pi Zero 2 W with Raspberry Pi OS Lite, get the 2.8" SPI TFT display showing pygame-rendered content, prove the buttons + touch + I2S DAC are all wired and working, and confirm MPD can play a test track to the wired DAC. Smallest meaningful "the device works" milestone.

**Architecture:** Single-Pi appliance. Dev machine (Windows) is the source of truth for project files; Pi receives them via rsync over Wi-Fi. Hardware sub-assemblies enabled one at a time, each with its own verification step. Hello-world pygame app proves the display + input pipeline end-to-end before we layer the real UI on top.

**Tech Stack:** Raspberry Pi OS Lite Bookworm (64-bit), Python 3.11, pygame 2.5+, `python-evdev`, `fbcp-ili9341` (DMA SPI→FB mirror), MPD 0.23+, ALSA, systemd.

**Prerequisites — hardware on the bench:**
- Raspberry Pi Zero 2 W
- 2.8" SPI TFT display with ILI9341 controller + XPT2046 touch controller (e.g., Adafruit PiTFT 2.8" Resistive, or the generic eBay/AliExpress "240x320 SPI TFT with touch" board — pinout must match an ILI9341 + XPT2046)
- PCM5102A I2S DAC breakout (e.g., Adafruit I2S 3W Stereo Speaker Bonnet without the amp, or any bare PCM5102A board)
- 8 momentary tactile buttons + 1 power button + wiring harness
- microSD card, 256 GB, A2-rated, high-endurance (SanDisk High Endurance recommended)
- microSD card reader for the dev machine
- USB micro-B cable for power
- 5V 2.5A regulated USB power supply
- Optional but very helpful: jumper wires, a small breadboard for initial wiring

**Prerequisites — software on the dev machine:**
- Raspberry Pi Imager (https://www.raspberrypi.com/software/)
- An SSH client (Windows: OpenSSH built into PowerShell works fine)
- rsync — install via WSL2, or use `scp`/`pscp` as a fallback. Tasks below assume `rsync` is available.
- Python 3.11+ for any dev-machine-side testing
- Git

---

## File Structure

Files this plan creates, with responsibility for each:

```
musi/
├── README.md                              # Project overview, quickstart
├── pyproject.toml                         # Python package + dev deps
├── .gitignore                             # Python + IDE noise
├── docs/
│   ├── HARDWARE.md                        # Wiring diagram and pin assignments
│   └── DEPLOY.md                          # How to push code from dev → Pi
├── pi/                                    # Files that live on the Pi (synced via rsync)
│   ├── config/
│   │   ├── config.txt.fragment            # Lines to append to /boot/firmware/config.txt
│   │   ├── cmdline.txt.fragment           # Lines for /boot/firmware/cmdline.txt
│   │   ├── mpd.conf                       # MPD service config
│   │   └── asound.conf                    # ALSA config pinning hw:0 = PCM5102A
│   ├── systemd/
│   │   ├── musi-hello.service             # Autostart for the hello pygame app
│   │   └── fbcp.service                   # Autostart for fbcp-ili9341
│   └── scripts/
│       ├── install-base.sh                # Install OS packages
│       ├── install-fbcp.sh                # Build + install fbcp-ili9341
│       ├── apply-config.sh                # Apply config fragments to /boot
│       └── verify-hw.sh                   # Smoke-check script
├── src/
│   └── musi/
│       ├── __init__.py
│       ├── __main__.py                    # python -m musi entry point
│       ├── hello.py                       # Hello-world pygame app
│       └── inputs.py                      # evdev input multiplexer
├── tests/
│   ├── __init__.py
│   ├── test_inputs.py                     # Unit tests for inputs module
│   └── test_hello.py                      # Smoke test using SDL2 dummy driver
└── deploy/
    └── deploy.sh                          # rsync source → pi:/opt/musi
```

**Pi-side filesystem layout after install:**
```
/opt/musi/                                 # Synced source, owned by 'musi' user
/etc/systemd/system/musi-hello.service
/etc/systemd/system/fbcp.service
/etc/mpd.conf                              # Customized
/boot/firmware/config.txt                  # Patched
/boot/firmware/cmdline.txt                 # Patched
```

---

## Task 1: Project skeleton on the dev machine

**Files:**
- Create: `D:\project\musi\README.md`
- Create: `D:\project\musi\pyproject.toml`
- Create: `D:\project\musi\.gitignore`
- Create: `D:\project\musi\src\musi\__init__.py`
- Create: `D:\project\musi\src\musi\__main__.py`
- Create: `D:\project\musi\tests\__init__.py`

- [ ] **Step 1: Initialize git repo**

```powershell
cd D:\project\musi
git init
git config user.name "Your Name"
git config user.email "you@example.com"
```

Expected: `Initialized empty Git repository in D:/project/musi/.git/`

- [ ] **Step 2: Create README.md**

```markdown
# musi

Custom iPod-style music player on a Raspberry Pi Zero 2 W.

See `docs/superpowers/specs/2026-05-14-musi-design.md` for full design.

## Quick start (dev)

1. Bench the hardware per `docs/HARDWARE.md`.
2. Flash the SD per `docs/DEPLOY.md`.
3. After SSH into the Pi: `sudo bash /opt/musi/pi/scripts/install-base.sh`.
4. From the dev machine: `bash deploy/deploy.sh`.
5. Run `python -m musi hello` on the Pi to verify the display.
```

- [ ] **Step 3: Create .gitignore**

```
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.venv/
.vscode/
.idea/
*.swp
.DS_Store
.superpowers/
```

- [ ] **Step 4: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "musi"
version = "0.1.0"
description = "Custom iPod-style music player for Raspberry Pi Zero 2 W"
requires-python = ">=3.11"
dependencies = [
    "pygame>=2.5",
    "evdev>=1.6",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 5: Create empty package files**

`src/musi/__init__.py`:
```python
__version__ = "0.1.0"
```

`src/musi/__main__.py`:
```python
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m musi <command>")
        print("Commands: hello")
        return 1
    cmd = sys.argv[1]
    if cmd == "hello":
        from musi.hello import run
        return run()
    print(f"Unknown command: {cmd}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

`tests/__init__.py`: (empty file)

- [ ] **Step 6: Verify package is importable**

```powershell
python -c "import sys; sys.path.insert(0, 'src'); import musi; print(musi.__version__)"
```

Expected: `0.1.0`

- [ ] **Step 7: Commit**

```powershell
git add README.md pyproject.toml .gitignore src/ tests/
git commit -m "chore: initial project skeleton"
```

---

## Task 2: Hardware wiring documentation

**Files:**
- Create: `D:\project\musi\docs\HARDWARE.md`

- [ ] **Step 1: Write the wiring guide**

`docs/HARDWARE.md`:

````markdown
# Hardware wiring — musi v1

## Pi Zero 2 W GPIO pinout (BCM numbering)

All pin numbers below are **BCM GPIO numbers** (not physical pin numbers). The Pi Zero 2 W has the same 40-pin header as a Pi 4.

## SPI TFT display (ILI9341) + Touch (XPT2046)

The display and touch share the SPI bus (SPI0) but have separate chip-select lines.

| Function | Pi BCM pin | Display pin label |
|---|---|---|
| VCC (3.3V) | 3V3 | VCC |
| GND | GND | GND |
| MOSI | GPIO 10 | SDI / DIN |
| MISO | GPIO 9 | SDO (display + touch share) |
| SCLK | GPIO 11 | SCK |
| Display CS | GPIO 8 (CE0) | LCD_CS / TFT_CS |
| Display DC | GPIO 25 | DC / RS |
| Display Reset | GPIO 24 | RST |
| Backlight | GPIO 18 | LED / BL |
| Touch CS | GPIO 7 (CE1) | T_CS |
| Touch IRQ | GPIO 17 | T_IRQ / PEN |

## PCM5102A I2S DAC

The PCM5102A is hardware-only — no I2C, just I2S in.

| Function | Pi BCM pin | DAC pin label |
|---|---|---|
| VCC (3.3V or 5V — see datasheet) | 3V3 or 5V | VIN |
| GND | GND | GND |
| BCK (bit clock) | GPIO 18* | BCK |
| LRCK (word select) | GPIO 19 | LRCK / LCK |
| DIN (data) | GPIO 21 | DIN |

\* GPIO 18 is shared between backlight PWM and I2S BCK. If you use I2S, you cannot PWM the backlight on this pin. For v1, drive the backlight from a different GPIO or tie it to 3V3 through a current-limiting resistor (200Ω) for always-on. The display config below uses GPIO 13 for backlight instead.

**Revised backlight pin to avoid conflict:**

| Backlight | GPIO 13 | LED / BL |

## Buttons (gpio-keys overlay)

All buttons connect between the listed GPIO and GND. Internal pull-ups enabled by the overlay. Pressed = low.

| Button | BCM GPIO | evdev keycode |
|---|---|---|
| D-pad up | GPIO 5 | KEY_UP |
| D-pad down | GPIO 6 | KEY_DOWN |
| D-pad left | GPIO 12 | KEY_LEFT |
| D-pad right | GPIO 16 | KEY_RIGHT |
| Select | GPIO 20 | KEY_ENTER |
| Back | GPIO 26 | KEY_ESC |
| Prev | GPIO 22 | KEY_PREVIOUSSONG |
| Next | GPIO 23 | KEY_NEXTSONG |
| Play/Pause | GPIO 27 | KEY_PLAYPAUSE |

## Power button

| Power button | GPIO 4 | KEY_POWER |

Wires between GPIO 4 and GND. Internal pull-up. Pressed = low.

## Pins summary (collision-checked)

Used: 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 17, 18 (I2S BCK), 19, 20, 21, 22, 23, 24, 25, 26, 27.
Free: 0, 1, 2, 3, 14, 15. Reserved (do not use): 14, 15 (UART for serial console).

## Wiring sanity checks

- Display must be 3.3V logic. **Never feed 5V into the SPI/control lines.**
- PCM5102A's FMT, DEMP, XSMT, FLT pins should be jumpered per the breakout's defaults (usually all to GND for 16/24-bit I2S, no de-emphasis, soft mute disabled).
- Add 100nF decoupling caps near the DAC's VCC pin.
- Use short jumper wires (≤15 cm) for SPI to keep signal integrity at the higher clock rates fbcp uses.

````

- [ ] **Step 2: Commit**

```powershell
git add docs/HARDWARE.md
git commit -m "docs: hardware wiring guide"
```

---

## Task 3: Flash SD card with Raspberry Pi OS Lite

**Files:** None on dev machine (this is a manual flash operation).

- [ ] **Step 1: Download Raspberry Pi Imager**

Open https://www.raspberrypi.com/software/ in a browser. Download "Raspberry Pi Imager for Windows" and install it.

- [ ] **Step 2: Flash the SD card**

Insert the 256 GB microSD into the dev machine via reader. In Raspberry Pi Imager:

1. Click **CHOOSE DEVICE** → "Raspberry Pi Zero 2 W"
2. Click **CHOOSE OS** → "Raspberry Pi OS (other)" → **"Raspberry Pi OS Lite (64-bit)"** (Bookworm)
3. Click **CHOOSE STORAGE** → your SD card reader
4. Click **NEXT** → **EDIT SETTINGS**
   - **General tab:**
     - Set hostname: `musi`
     - Set username: `musi`, password: pick something memorable
     - Configure wireless LAN: enter your SSID + WPA password, country `US` (or your country code)
     - Set locale: your timezone, keyboard layout
   - **Services tab:**
     - ✅ Enable SSH → "Use password authentication"
   - Click **SAVE**
5. Click **YES** to "Apply OS customisation settings?"
6. Click **YES** to confirm erase + write.

Wait for the flash to complete (~5 minutes) and the verification pass (~3 minutes).

- [ ] **Step 3: Eject the SD card**

Use Windows' Safely Remove Hardware to eject. Insert into the Pi Zero 2 W.

- [ ] **Step 4: First boot**

Connect the 5V USB power supply. Wait ~60 seconds for first-boot expansion + Wi-Fi connection.

- [ ] **Step 5: Find the Pi on the network and SSH in**

```powershell
ssh musi@musi.local
```

If `musi.local` doesn't resolve (Windows mDNS can be flaky), find the IP:
```powershell
arp -a | findstr "b8-27-eb\|dc-a6-32\|e4-5f-01\|d8-3a-dd"
```

Then `ssh musi@<ip>`. Accept the fingerprint, enter the password.

Expected prompt:
```
musi@musi:~ $
```

- [ ] **Step 6: Update the system**

On the Pi:
```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

Wait ~30 seconds, then SSH back in.

---

## Task 4: Install base packages on the Pi

**Files:**
- Create: `D:\project\musi\pi\scripts\install-base.sh`

- [ ] **Step 1: Write the install script**

`pi/scripts/install-base.sh`:

```bash
#!/usr/bin/env bash
# Install base OS packages required by musi. Idempotent.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo." >&2
    exit 1
fi

apt update
apt install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    python3-pygame \
    python3-evdev \
    python3-mpd2 \
    python3-pil \
    python3-mutagen \
    git \
    rsync \
    build-essential \
    cmake \
    libraspberrypi-dev \
    raspberrypi-kernel-headers \
    device-tree-compiler \
    mpd \
    mpc \
    alsa-utils \
    evtest \
    i2c-tools

# Create the musi user (if it doesn't exist) with the right groups
if ! id -u musi >/dev/null 2>&1; then
    useradd -m -s /bin/bash musi
fi
usermod -a -G audio,video,input,gpio,spi,i2c,plugdev musi

# Create the install target
install -d -o musi -g musi /opt/musi

echo "Base packages installed. Reboot recommended."
```

- [ ] **Step 2: Make it executable + commit**

```powershell
# On the dev machine; line endings matter for shell scripts
git add pi/scripts/install-base.sh
git update-index --chmod=+x pi/scripts/install-base.sh
git commit -m "feat(pi): base package install script"
```

- [ ] **Step 3: Copy the script to the Pi and run it**

From dev machine:
```powershell
scp pi/scripts/install-base.sh musi@musi.local:/tmp/install-base.sh
ssh musi@musi.local "chmod +x /tmp/install-base.sh && sudo /tmp/install-base.sh"
```

Expected: package installs complete without errors.

- [ ] **Step 4: Verify**

On the Pi:
```bash
groups
```

Expected: includes `audio video input gpio spi i2c plugdev`.

```bash
ls -ld /opt/musi
```

Expected: `drwxr-xr-x 2 musi musi ... /opt/musi`

---

## Task 5: Enable SPI, I2C, I2S, and disable HDMI/Wi-Fi power-save in /boot/firmware/config.txt

**Files:**
- Create: `D:\project\musi\pi\config\config.txt.fragment`
- Create: `D:\project\musi\pi\scripts\apply-config.sh`

- [ ] **Step 1: Write the config fragment**

`pi/config/config.txt.fragment`:

```
# === musi additions === BEGIN
# Generated by pi/scripts/apply-config.sh; everything between BEGIN and END
# markers is managed by that script. Edit the fragment file instead.

# Enable SPI for the TFT display + touch
dtparam=spi=on

# Enable I2C for future fuel gauge / addressable peripherals
dtparam=i2c_arm=on

# Enable I2S for the PCM5102A DAC
dtparam=i2s=on
dtoverlay=hifiberry-dac

# Enable GPIO buttons via gpio-keys overlay (one button per GPIO).
# Active-low with internal pull-ups.
dtoverlay=gpio-key,gpio=5,keycode=103,label="UP"
dtoverlay=gpio-key,gpio=6,keycode=108,label="DOWN"
dtoverlay=gpio-key,gpio=12,keycode=105,label="LEFT"
dtoverlay=gpio-key,gpio=16,keycode=106,label="RIGHT"
dtoverlay=gpio-key,gpio=20,keycode=28,label="SELECT"
dtoverlay=gpio-key,gpio=26,keycode=1,label="BACK"
dtoverlay=gpio-key,gpio=22,keycode=165,label="PREV"
dtoverlay=gpio-key,gpio=23,keycode=163,label="NEXT"
dtoverlay=gpio-key,gpio=27,keycode=164,label="PLAYPAUSE"
dtoverlay=gpio-key,gpio=4,keycode=116,label="POWER"

# Enable XPT2046 touch controller on SPI0 CE1.
# pmax=255 sets the maximum pressure threshold above which events are filtered.
dtoverlay=ads7846,cs=1,penirq=17,penirq_pull=2,speed=1000000,keep_vref_on=1,swapxy=0,pmax=255,xohms=150

# Disable HDMI to save power (corded for now, but habit)
dtoverlay=disable-bt

# Faster boot
disable_splash=1
boot_delay=0
# === musi additions === END
```

> **Note on `hifiberry-dac`:** This overlay is the standard way to enable a generic PCM5102A I2S DAC on Pi. It does not require the actual HiFiBerry hardware.
>
> **Note on `disable-bt`:** Bluetooth on the Pi Zero 2 W is wired to the same UART as the serial console. Disabling it for now both saves power and frees the UART. Re-enable in Plan 07 when BT audio is implemented.

- [ ] **Step 2: Write the apply-config script**

`pi/scripts/apply-config.sh`:

```bash
#!/usr/bin/env bash
# Idempotently apply musi's config.txt fragment.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo." >&2
    exit 1
fi

CONFIG=/boot/firmware/config.txt
if [[ ! -f $CONFIG ]]; then
    # Older images had it at /boot/config.txt
    CONFIG=/boot/config.txt
fi

FRAGMENT=$(dirname "$0")/../config/config.txt.fragment
if [[ ! -f $FRAGMENT ]]; then
    echo "Fragment not found at $FRAGMENT" >&2
    exit 1
fi

BACKUP=${CONFIG}.musi-backup
if [[ ! -f $BACKUP ]]; then
    cp "$CONFIG" "$BACKUP"
fi

# Remove any existing musi block
python3 - "$CONFIG" <<'PY'
import sys, re
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    text = f.read()
text = re.sub(
    r"# === musi additions === BEGIN.*?# === musi additions === END\n?",
    "",
    text,
    flags=re.DOTALL,
)
with open(path, "w", encoding="utf-8") as f:
    f.write(text)
PY

# Append the fragment
cat "$FRAGMENT" >> "$CONFIG"

echo "Applied musi config fragment to $CONFIG"
echo "Reboot required for kernel-level changes."
```

- [ ] **Step 3: Commit**

```powershell
git add pi/config/config.txt.fragment pi/scripts/apply-config.sh
git update-index --chmod=+x pi/scripts/apply-config.sh
git commit -m "feat(pi): config.txt fragment for SPI/I2S/buttons/touch"
```

- [ ] **Step 4: Deploy + apply on the Pi**

```powershell
scp -r pi musi@musi.local:/tmp/musi-pi
ssh musi@musi.local "sudo /tmp/musi-pi/scripts/apply-config.sh"
```

- [ ] **Step 5: Reboot and verify**

```bash
ssh musi@musi.local "sudo reboot"
```

Wait 30s, SSH back in, then:

```bash
ls /dev/spidev*
ls /dev/i2c*
aplay -l
ls /dev/input/event*
```

Expected:
- `/dev/spidev0.0` and `/dev/spidev0.1` exist
- `/dev/i2c-1` exists
- `aplay -l` shows a card named `sndrpihifiberry` or similar with `snd_rpi_hifiberry_dac`
- multiple `event*` devices (one per gpio-key)

---

## Task 6: Install and configure fbcp-ili9341 (display driver)

**Files:**
- Create: `D:\project\musi\pi\scripts\install-fbcp.sh`
- Create: `D:\project\musi\pi\systemd\fbcp.service`

The original `fbcp` is too slow for our display. `fbcp-ili9341` by juj is the canonical fast driver — it uses DMA to push framebuffer pixels over SPI at up to 60+ FPS for ILI9341 panels.

- [ ] **Step 1: Write the install script**

`pi/scripts/install-fbcp.sh`:

```bash
#!/usr/bin/env bash
# Build and install fbcp-ili9341 from source. Idempotent.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo." >&2
    exit 1
fi

SRC_DIR=/usr/local/src/fbcp-ili9341

if [[ ! -d $SRC_DIR ]]; then
    git clone --depth 1 https://github.com/juj/fbcp-ili9341.git "$SRC_DIR"
fi

cd "$SRC_DIR"

# Clean any previous build
rm -rf build
mkdir -p build
cd build

# Build for ILI9341 240x320, SPI bus 0 CE0, DMA enabled.
# DC pin = GPIO 25 (matches hardware doc).
# Reset pin = GPIO 24.
# Backlight not managed by fbcp here — kept always-on via wiring.
# SPI clock 60 MHz is a safe upper bound for ILI9341 on Pi Zero 2.
cmake \
    -DARMV8A=ON \
    -DILI9341=ON \
    -DSPI_BUS_CLOCK_DIVISOR=6 \
    -DGPIO_TFT_DATA_CONTROL=25 \
    -DGPIO_TFT_RESET_PIN=24 \
    -DSTATISTICS=0 \
    -DUSE_DMA_TRANSFERS=ON \
    -DBACKLIGHT_CONTROL=OFF \
    -DDISPLAY_ROTATE_180_DEGREES=OFF \
    ..

make -j$(nproc)

install -m 0755 fbcp-ili9341 /usr/local/bin/fbcp-ili9341

echo "fbcp-ili9341 installed at /usr/local/bin/fbcp-ili9341"
```

- [ ] **Step 2: Write the systemd unit**

`pi/systemd/fbcp.service`:

```ini
[Unit]
Description=fbcp-ili9341 SPI display mirror
After=local-fs.target
Before=getty@tty1.service musi-hello.service

[Service]
Type=simple
ExecStart=/usr/local/bin/fbcp-ili9341
Restart=on-failure
RestartSec=2
StartLimitBurst=5
Nice=-5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Commit**

```powershell
git add pi/scripts/install-fbcp.sh pi/systemd/fbcp.service
git update-index --chmod=+x pi/scripts/install-fbcp.sh
git commit -m "feat(pi): fbcp-ili9341 install + systemd unit"
```

- [ ] **Step 4: Deploy + install on the Pi**

```powershell
scp -r pi musi@musi.local:/tmp/musi-pi
ssh musi@musi.local "sudo /tmp/musi-pi/scripts/install-fbcp.sh"
```

Build will take ~3-5 minutes on a Pi Zero 2 W.

- [ ] **Step 5: Install + enable systemd unit**

```bash
ssh musi@musi.local "sudo cp /tmp/musi-pi/systemd/fbcp.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable fbcp.service"
```

- [ ] **Step 6: Smoke-test the display**

```bash
ssh musi@musi.local "sudo systemctl start fbcp.service"
sleep 2
ssh musi@musi.local "sudo systemctl status fbcp.service --no-pager"
```

Expected: `active (running)`. The display should now mirror `/dev/fb0`. If the Pi was booted without HDMI, `/dev/fb0` will be the default 640x480 console framebuffer — and you should see the boot login prompt on the TFT (probably truncated / huge text — that's fine for now).

- [ ] **Step 7: Force a clean test pattern to verify**

```bash
ssh musi@musi.local "sudo dd if=/dev/urandom of=/dev/fb0 bs=1k count=200 2>/dev/null; sleep 1; sudo dd if=/dev/zero of=/dev/fb0 bs=1k count=200 2>/dev/null"
```

Expected: the TFT briefly shows static noise, then goes black. If yes, the display path works. If not, see Troubleshooting at end of Task 6.

**Troubleshooting:**
- White screen, no content: SPI is initializing but no data is being pushed. Check `journalctl -u fbcp.service` for errors. Likely cause: wrong DC pin (GPIO 25 expected).
- Garbled colors: SPI clock too fast — increase `SPI_BUS_CLOCK_DIVISOR` to 8 in install-fbcp.sh and rebuild.
- Black screen, no backlight: check the backlight wiring; backlight should be on always (pulled to 3V3 through a current-limiting resistor, or wired to GPIO 13 set high).

---

## Task 7: Verify touch input

**Files:** None (verification only).

- [ ] **Step 1: List input devices on the Pi**

```bash
ssh musi@musi.local "cat /proc/bus/input/devices | grep -A 4 -i ads7846"
```

Expected output includes a section like:
```
I: Bus=0006 Vendor=0000 Product=0000 Version=0000
N: Name="ADS7846 Touchscreen"
P: Phys=spi0.1/input0
S: Sysfs=/devices/platform/soc/.../input/inputN
H: Handlers=event0 ...
```

Note the `event*` number for ADS7846.

- [ ] **Step 2: Run evtest on the touch device**

```bash
ssh -t musi@musi.local "sudo evtest /dev/input/eventN"  # replace N with the touch event number
```

Touch the screen with a stylus or fingernail. Expected: events like:
```
Event: time ..., type 3 (EV_ABS), code 0 (ABS_X), value 1832
Event: time ..., type 3 (EV_ABS), code 1 (ABS_Y), value 2031
Event: time ..., type 1 (EV_KEY), code 330 (BTN_TOUCH), value 1
```

Raw ABS_X / ABS_Y values are in the controller's coordinate space (typically 0-4095), not pixel space. Calibration (mapping raw → screen pixels) will be done later in Plan 03. For now, "events arrive" is sufficient.

Press Ctrl+C to exit evtest.

**Troubleshooting:**
- No `ADS7846 Touchscreen` device: check `dmesg | grep ads7846`. Common causes: T_IRQ wired to wrong GPIO (should be 17), CS wired to wrong CE pin (should be CE1), or the overlay didn't load (check `vcgencmd get_config str | grep ads7846`).
- Events not arriving despite touch: T_IRQ wiring issue. Touch the screen *firmly* — resistive panels need real pressure.

---

## Task 8: Verify button input

**Files:** None (verification only).

- [ ] **Step 1: Identify the gpio-keys device**

```bash
ssh musi@musi.local "cat /proc/bus/input/devices | grep -A 4 -i gpio-keys"
```

Note the event number(s).

- [ ] **Step 2: evtest each button**

```bash
ssh -t musi@musi.local "sudo evtest /dev/input/event0"  # adjust to gpio-keys device
```

Press each button in turn. Expected: each press emits `EV_KEY` events with the keycode matching `docs/HARDWARE.md`.

If a single device contains all 10 buttons, evtest will report all of them. If each `gpio-key` overlay registered its own input device, you'll need to test them individually.

Verify each of the 10 buttons reports an event. Cross-check against the keycode table:

| Button | Expected keycode (decimal / name) |
|---|---|
| UP | 103 / KEY_UP |
| DOWN | 108 / KEY_DOWN |
| LEFT | 105 / KEY_LEFT |
| RIGHT | 106 / KEY_RIGHT |
| SELECT | 28 / KEY_ENTER |
| BACK | 1 / KEY_ESC |
| PREV | 165 / KEY_PREVIOUSSONG |
| NEXT | 163 / KEY_NEXTSONG |
| PLAYPAUSE | 164 / KEY_PLAYPAUSE |
| POWER | 116 / KEY_POWER |

Press Ctrl+C to exit.

**Troubleshooting:**
- A button reports nothing: check wiring with a multimeter (continuity from GPIO to GND when pressed).
- Multiple buttons fire on a single press: solder bridge or cross-wired pins.

---

## Task 9: Verify audio output via aplay + MPD

**Files:**
- Create: `D:\project\musi\pi\config\asound.conf`
- Create: `D:\project\musi\pi\config\mpd.conf`

- [ ] **Step 1: Write ALSA config**

`pi/config/asound.conf`:

```
# Pin the HiFiBerry DAC (PCM5102A) as the default ALSA card.
pcm.!default {
    type hw
    card sndrpihifiberry
}

ctl.!default {
    type hw
    card sndrpihifiberry
}
```

- [ ] **Step 2: Write MPD config**

`pi/config/mpd.conf`:

```
music_directory     "/tmp/musi-music"
playlist_directory  "/var/lib/mpd/playlists"
db_file             "/var/lib/mpd/tag_cache"
log_file            "syslog"
state_file          "/var/lib/mpd/state"
sticker_file        "/var/lib/mpd/sticker.sql"
user                "mpd"
bind_to_address     "127.0.0.1"
port                "6600"
auto_update         "yes"

# Use software mixer (PCM5102A has no hardware volume)
audio_output {
    type            "alsa"
    name            "PCM5102A DAC"
    device          "hw:sndrpihifiberry,0"
    mixer_type      "software"
}

# Replay-gain
replaygain          "auto"
replaygain_preamp   "0"
```

- [ ] **Step 3: Commit**

```powershell
git add pi/config/asound.conf pi/config/mpd.conf
git commit -m "feat(pi): ALSA + MPD config for PCM5102A"
```

- [ ] **Step 4: Deploy configs**

```powershell
scp -r pi musi@musi.local:/tmp/musi-pi
ssh musi@musi.local "sudo cp /tmp/musi-pi/config/asound.conf /etc/asound.conf && sudo cp /tmp/musi-pi/config/mpd.conf /etc/mpd.conf"
ssh musi@musi.local "sudo mkdir -p /tmp/musi-music && sudo chown mpd:audio /tmp/musi-music"
```

- [ ] **Step 5: Quick aplay smoke test**

On the Pi:
```bash
ssh musi@musi.local "speaker-test -t sine -f 440 -c 2 -D default -l 1 -s 1"
```

Plug headphones into the DAC's 3.5mm output. Expected: a 440 Hz sine tone in both ears for ~1 second.

**Troubleshooting:**
- No sound, no errors: check the DAC's wiring (BCK=18, LRCK=19, DIN=21). Run `aplay -l` to confirm the card exists.
- Hum/static: check power supply quality. PCM5102A is sensitive to noisy 3V3 rails.
- Sound only in one ear: typically a wiring or solder issue on the DAC's analog output side.

- [ ] **Step 6: Put a test track on the Pi and play through MPD**

You need a test file. Use a CC-licensed sample (or any local MP3/FLAC you have):

From dev machine:
```powershell
# If you don't have one handy, download a CC0 sample:
# curl -L -o test.mp3 https://files.freemusicarchive.org/storage-freemusicarchive-org/music/no_curator/Komiku/Its_time_for_adventure_vol_2/Komiku_-_06_-_Battle_Of_Pogs.mp3
scp test.mp3 musi@musi.local:/tmp/musi-music/test.mp3
```

On the Pi:
```bash
ssh musi@musi.local "sudo systemctl restart mpd"
sleep 2
ssh musi@musi.local "mpc update && sleep 1 && mpc add test.mp3 && mpc play"
```

Expected: the test track plays through headphones at moderate volume.

```bash
ssh musi@musi.local "mpc stop"
```

---

## Task 10: Create the hello-world pygame app

**Files:**
- Create: `D:\project\musi\src\musi\hello.py`
- Create: `D:\project\musi\src\musi\inputs.py`
- Create: `D:\project\musi\tests\test_inputs.py`
- Create: `D:\project\musi\tests\test_hello.py`

- [ ] **Step 1: Write a failing test for the input multiplexer**

`tests/test_inputs.py`:

```python
"""Tests for the evdev input multiplexer."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from musi.inputs import (
    ButtonEvent,
    TouchEvent,
    InputMultiplexer,
    button_for_keycode,
)


def test_button_for_keycode_maps_dpad_up() -> None:
    assert button_for_keycode(103) == "up"


def test_button_for_keycode_maps_select() -> None:
    assert button_for_keycode(28) == "select"


def test_button_for_keycode_returns_none_for_unknown() -> None:
    assert button_for_keycode(9999) is None


def test_multiplexer_yields_button_event_on_keypress() -> None:
    # Simulate one evdev KEY event: KEY_UP pressed.
    fake_event = MagicMock()
    fake_event.type = 1  # EV_KEY
    fake_event.code = 103  # KEY_UP
    fake_event.value = 1  # pressed

    mux = InputMultiplexer.__new__(InputMultiplexer)  # bypass __init__
    result = mux._translate(fake_event)

    assert isinstance(result, ButtonEvent)
    assert result.button == "up"
    assert result.pressed is True


def test_multiplexer_yields_button_event_on_release() -> None:
    fake_event = MagicMock()
    fake_event.type = 1
    fake_event.code = 28  # KEY_ENTER → select
    fake_event.value = 0  # released

    mux = InputMultiplexer.__new__(InputMultiplexer)
    result = mux._translate(fake_event)

    assert isinstance(result, ButtonEvent)
    assert result.button == "select"
    assert result.pressed is False


def test_multiplexer_ignores_key_repeat_events() -> None:
    fake_event = MagicMock()
    fake_event.type = 1
    fake_event.code = 103
    fake_event.value = 2  # held / auto-repeat

    mux = InputMultiplexer.__new__(InputMultiplexer)
    result = mux._translate(fake_event)

    assert result is None


def test_multiplexer_yields_touch_event_on_abs_with_pressure() -> None:
    # The multiplexer accumulates ABS_X / ABS_Y / BTN_TOUCH across a packet
    # and emits a TouchEvent on the SYN_REPORT. We exercise that here with
    # the public API: pass a sequence of events, check what comes out.
    mux = InputMultiplexer.__new__(InputMultiplexer)
    mux._touch_state = {"x": None, "y": None, "down": False}

    abs_x = MagicMock(); abs_x.type = 3; abs_x.code = 0; abs_x.value = 2000
    abs_y = MagicMock(); abs_y.type = 3; abs_y.code = 1; abs_y.value = 1500
    btn_touch = MagicMock(); btn_touch.type = 1; btn_touch.code = 330; btn_touch.value = 1
    syn = MagicMock(); syn.type = 0  # SYN_REPORT

    assert mux._translate(abs_x) is None
    assert mux._translate(abs_y) is None
    assert mux._translate(btn_touch) is None
    out = mux._translate(syn)

    assert isinstance(out, TouchEvent)
    assert out.x_raw == 2000
    assert out.y_raw == 1500
    assert out.pressed is True
```

- [ ] **Step 2: Run the test to verify it fails**

```powershell
cd D:\project\musi
python -m pytest tests/test_inputs.py -v
```

Expected: ImportError or `ModuleNotFoundError: No module named 'musi.inputs'`.

- [ ] **Step 3: Implement the inputs module**

`src/musi/inputs.py`:

```python
"""Multiplex evdev button + touch events into a single typed event stream."""
from __future__ import annotations

import select
from dataclasses import dataclass
from typing import Iterator, Optional, Sequence

# evdev event type constants (from linux/input-event-codes.h)
EV_SYN = 0
EV_KEY = 1
EV_ABS = 3

# evdev code constants we care about
KEY_ESC = 1
KEY_ENTER = 28
KEY_POWER = 116
KEY_UP = 103
KEY_DOWN = 108
KEY_LEFT = 105
KEY_RIGHT = 106
KEY_PREVIOUSSONG = 165
KEY_NEXTSONG = 163
KEY_PLAYPAUSE = 164

ABS_X = 0
ABS_Y = 1
BTN_TOUCH = 330


# Mapping evdev keycodes → our internal button names.
# These names form the input contract for the rest of the application.
_KEYCODE_TO_BUTTON = {
    KEY_UP: "up",
    KEY_DOWN: "down",
    KEY_LEFT: "left",
    KEY_RIGHT: "right",
    KEY_ENTER: "select",
    KEY_ESC: "back",
    KEY_PREVIOUSSONG: "prev",
    KEY_NEXTSONG: "next",
    KEY_PLAYPAUSE: "play_pause",
    KEY_POWER: "power",
}


def button_for_keycode(code: int) -> Optional[str]:
    """Return the musi button name for a Linux keycode, or None if unmapped."""
    return _KEYCODE_TO_BUTTON.get(code)


@dataclass(frozen=True)
class ButtonEvent:
    button: str
    pressed: bool


@dataclass(frozen=True)
class TouchEvent:
    x_raw: int
    y_raw: int
    pressed: bool


class InputMultiplexer:
    """Read from button + touch evdev devices, yield unified events.

    Caller passes the device paths. The class opens them with `evdev.InputDevice`
    and exposes an iterator. Touch packets are reassembled across multiple
    EV_ABS / EV_KEY events into a single TouchEvent on SYN_REPORT.
    """

    def __init__(self, button_device_paths: Sequence[str], touch_device_path: Optional[str]) -> None:
        import evdev  # local import so unit tests can stub it
        self._devices = [evdev.InputDevice(p) for p in button_device_paths]
        if touch_device_path is not None:
            self._touch = evdev.InputDevice(touch_device_path)
            self._devices.append(self._touch)
        else:
            self._touch = None
        self._touch_state: dict = {"x": None, "y": None, "down": False}

    def events(self) -> Iterator:
        """Yield ButtonEvent / TouchEvent forever. Blocking on idle."""
        fds_to_devices = {d.fd: d for d in self._devices}
        while True:
            r, _, _ = select.select(fds_to_devices.keys(), [], [])
            for fd in r:
                for raw in fds_to_devices[fd].read():
                    result = self._translate(raw)
                    if result is not None:
                        yield result

    def _translate(self, evt) -> Optional[object]:
        if evt.type == EV_KEY:
            if evt.value == 2:  # auto-repeat — ignore for now
                return None
            if evt.code == BTN_TOUCH:
                self._touch_state["down"] = bool(evt.value)
                return None
            name = button_for_keycode(evt.code)
            if name is None:
                return None
            return ButtonEvent(button=name, pressed=bool(evt.value))

        if evt.type == EV_ABS:
            if evt.code == ABS_X:
                self._touch_state["x"] = evt.value
            elif evt.code == ABS_Y:
                self._touch_state["y"] = evt.value
            return None

        if evt.type == EV_SYN:
            state = self._touch_state
            if state["x"] is None or state["y"] is None:
                return None
            te = TouchEvent(x_raw=state["x"], y_raw=state["y"], pressed=state["down"])
            # Keep x/y so we can emit drag updates; reset only on full release packet
            if not state["down"]:
                state["x"] = None
                state["y"] = None
            return te

        return None
```

- [ ] **Step 4: Run the tests, verify they pass**

```powershell
python -m pytest tests/test_inputs.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Write the hello-world test**

`tests/test_hello.py`:

```python
"""Smoke test for the hello pygame app using the SDL2 dummy video driver.

Runs the render loop for one frame with synthetic input and verifies it doesn't
crash. The actual visual is verified manually on the device.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _force_dummy_video(monkeypatch):
    """Run pygame headlessly during tests."""
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")


def test_hello_renders_one_frame_without_crashing() -> None:
    from musi.hello import _render_one_frame
    import pygame
    pygame.init()
    surface = pygame.display.set_mode((240, 320))
    # Renders the hello screen with given last input description
    _render_one_frame(surface, last_input="(no input yet)")
    # Reach a known-clean exit
    pygame.quit()
```

- [ ] **Step 6: Run the hello test, verify it fails**

```powershell
python -m pytest tests/test_hello.py -v
```

Expected: `ModuleNotFoundError` for `musi.hello`.

- [ ] **Step 7: Implement the hello pygame app**

`src/musi/hello.py`:

```python
"""Hello-world pygame app: prove the display + input pipeline end-to-end.

Renders a 240x320 screen with:
- Project name + version
- Last input description (button name or touch coords)
- A small filled rectangle that moves when the D-pad is pressed

Exits cleanly on `back` button (KEY_ESC) or pygame quit.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import pygame

from musi import __version__
from musi.inputs import ButtonEvent, InputMultiplexer, TouchEvent

SCREEN_W = 240
SCREEN_H = 320
DOT_RADIUS = 8
DOT_STEP = 12

WHITE = (245, 245, 245)
BG = (12, 14, 18)
ACCENT = (255, 126, 95)
SUBTLE = (140, 140, 150)


def _render_one_frame(
    surface: pygame.Surface,
    last_input: str,
    dot_x: int = SCREEN_W // 2,
    dot_y: int = SCREEN_H // 2,
) -> None:
    surface.fill(BG)
    font_lg = pygame.font.SysFont(None, 28)
    font_md = pygame.font.SysFont(None, 18)
    font_sm = pygame.font.SysFont(None, 14)

    title = font_lg.render("musi", True, WHITE)
    surface.blit(title, (12, 12))

    version = font_sm.render(f"v{__version__} — hello", True, SUBTLE)
    surface.blit(version, (12, 40))

    label = font_md.render("Last input:", True, SUBTLE)
    surface.blit(label, (12, 80))

    value = font_md.render(last_input, True, WHITE)
    surface.blit(value, (12, 102))

    pygame.draw.circle(surface, ACCENT, (dot_x, dot_y), DOT_RADIUS)

    footer = font_sm.render("BACK to exit", True, SUBTLE)
    surface.blit(footer, (12, SCREEN_H - 22))


def _discover_evdev_paths() -> tuple[list[str], Optional[str]]:
    """Find button + touch device paths under /dev/input via /proc.

    Returns (button_paths, touch_path_or_none).
    """
    import re
    info = Path("/proc/bus/input/devices").read_text()
    blocks = info.split("\n\n")

    button_paths: list[str] = []
    touch_path: Optional[str] = None

    for block in blocks:
        name_match = re.search(r"^N: Name=\"(.+)\"", block, flags=re.MULTILINE)
        handlers_match = re.search(r"^H: Handlers=([^\n]+)", block, flags=re.MULTILINE)
        if not name_match or not handlers_match:
            continue
        name = name_match.group(1)
        handlers = handlers_match.group(1).split()
        event_name = next((h for h in handlers if h.startswith("event")), None)
        if event_name is None:
            continue
        dev_path = f"/dev/input/{event_name}"
        if "ADS7846" in name or "Touchscreen" in name:
            touch_path = dev_path
        elif "gpio" in name.lower() or "key" in name.lower():
            button_paths.append(dev_path)

    return button_paths, touch_path


def run() -> int:
    # Use /dev/fb0 (which fbcp mirrors to the SPI display)
    os.environ.setdefault("SDL_VIDEODRIVER", "fbcon")
    os.environ.setdefault("SDL_FBDEV", "/dev/fb0")
    os.environ.setdefault("SDL_AUDIODRIVER", "alsa")
    pygame.init()
    surface = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.mouse.set_visible(False)
    pygame.display.set_caption("musi hello")

    button_paths, touch_path = _discover_evdev_paths()
    if not button_paths:
        print("WARNING: no button input devices found", file=sys.stderr)
    if touch_path is None:
        print("WARNING: no touch input device found", file=sys.stderr)

    mux: Optional[InputMultiplexer] = None
    if button_paths or touch_path:
        mux = InputMultiplexer(button_paths, touch_path)

    last_input = "(waiting for input)"
    dot_x, dot_y = SCREEN_W // 2, SCREEN_H // 2
    clock = pygame.time.Clock()
    running = True

    # Pump events from the mux on a background-ish read; for v1 we read
    # non-blocking by polling the file descriptors via select with timeout 0.
    import select as _sel

    while running:
        # Drain mux events (non-blocking)
        if mux is not None:
            fds = [d.fd for d in mux._devices]
            ready, _, _ = _sel.select(fds, [], [], 0)
            for fd in ready:
                dev = next(d for d in mux._devices if d.fd == fd)
                for raw in dev.read():
                    evt = mux._translate(raw)
                    if evt is None:
                        continue
                    if isinstance(evt, ButtonEvent):
                        if not evt.pressed:
                            continue
                        last_input = f"button: {evt.button}"
                        if evt.button == "back":
                            running = False
                        elif evt.button == "up":
                            dot_y = max(DOT_RADIUS, dot_y - DOT_STEP)
                        elif evt.button == "down":
                            dot_y = min(SCREEN_H - DOT_RADIUS, dot_y + DOT_STEP)
                        elif evt.button == "left":
                            dot_x = max(DOT_RADIUS, dot_x - DOT_STEP)
                        elif evt.button == "right":
                            dot_x = min(SCREEN_W - DOT_RADIUS, dot_x + DOT_STEP)
                    elif isinstance(evt, TouchEvent):
                        last_input = f"touch: ({evt.x_raw}, {evt.y_raw}) {'down' if evt.pressed else 'up'}"

        # Pygame's own events (window close in dev env)
        for pyevt in pygame.event.get():
            if pyevt.type == pygame.QUIT:
                running = False

        _render_one_frame(surface, last_input, dot_x, dot_y)
        pygame.display.flip()
        clock.tick(30)

    pygame.quit()
    return 0
```

- [ ] **Step 8: Run the hello test, verify it passes**

```powershell
python -m pytest tests/test_hello.py -v
```

Expected: PASS.

- [ ] **Step 9: Run the full test suite**

```powershell
python -m pytest -v
```

Expected: all tests PASS.

- [ ] **Step 10: Commit**

```powershell
git add src/musi/inputs.py src/musi/hello.py tests/test_inputs.py tests/test_hello.py
git commit -m "feat: hello pygame app + evdev input multiplexer"
```

---

## Task 11: Deploy script (rsync dev → Pi)

**Files:**
- Create: `D:\project\musi\deploy\deploy.sh`
- Create: `D:\project\musi\docs\DEPLOY.md`

- [ ] **Step 1: Write the deploy script**

`deploy/deploy.sh`:

```bash
#!/usr/bin/env bash
# Sync project source from the dev machine to the Pi.
# Run from the project root: bash deploy/deploy.sh
set -euo pipefail

PI_HOST="${PI_HOST:-musi@musi.local}"
PI_PATH="/opt/musi"

echo "Deploying to $PI_HOST:$PI_PATH ..."

# --delete keeps the remote a perfect mirror of the local working tree's
# tracked files. We exclude dev-only paths.
rsync -av --delete \
    --exclude '.git/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude '.venv/' \
    --exclude 'docs/superpowers/' \
    --exclude '.superpowers/' \
    --exclude 'deploy/' \
    ./ "$PI_HOST:$PI_PATH/"

echo "Done."
```

- [ ] **Step 2: Write deploy docs**

`docs/DEPLOY.md`:

```markdown
# Deploy

## From dev machine to Pi

```powershell
# In WSL or Git Bash:
bash deploy/deploy.sh
```

Override the Pi host with the env var:
```powershell
$env:PI_HOST = "musi@192.168.1.42"; bash deploy/deploy.sh
```

## Running the hello app

After deploy, SSH in and run:

```bash
ssh musi@musi.local
cd /opt/musi
python3 -m musi hello
```

The display should show the musi hello screen. Press the D-pad to move the dot. Press BACK to exit.
```

- [ ] **Step 3: Commit**

```powershell
git add deploy/deploy.sh docs/DEPLOY.md
git update-index --chmod=+x deploy/deploy.sh
git commit -m "feat: rsync deploy script + docs"
```

- [ ] **Step 4: Deploy + run on the Pi**

From dev machine (WSL or Git Bash):
```bash
bash deploy/deploy.sh
```

Expected: rsync output showing files transferred.

On the Pi, run the hello app:
```bash
ssh musi@musi.local "cd /opt/musi && sudo python3 -m musi hello"
```

(Sudo is required to read evdev devices in the default Pi OS config. We'll fix permissions via udev rules in a later task.)

**Look at the SPI display.** Expected:
- Black background
- "musi" title in white
- Version subtitle "v0.1.0 — hello"
- A "Last input:" label
- An orange dot in the middle of the screen

**Press the buttons.** Expected:
- The orange dot moves with the D-pad
- "Last input:" updates to show which button was pressed
- BACK exits the app

**Touch the screen.** Expected:
- "Last input:" shows raw `(x, y) down`/`up` coordinates

---

## Task 12: udev rule for non-root evdev access

**Files:**
- Create: `D:\project\musi\pi\config\99-musi-input.rules`
- Create: `D:\project\musi\pi\scripts\install-udev.sh`

- [ ] **Step 1: Write the udev rule**

`pi/config/99-musi-input.rules`:

```
# Grant the musi user access to input devices without sudo.
KERNEL=="event*", SUBSYSTEM=="input", GROUP="input", MODE="0660"
```

- [ ] **Step 2: Write the install script**

`pi/scripts/install-udev.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo." >&2
    exit 1
fi

SRC=$(dirname "$0")/../config/99-musi-input.rules
install -m 0644 "$SRC" /etc/udev/rules.d/99-musi-input.rules
udevadm control --reload-rules
udevadm trigger --subsystem-match=input

echo "udev rule installed and reloaded."
```

- [ ] **Step 3: Commit**

```powershell
git add pi/config/99-musi-input.rules pi/scripts/install-udev.sh
git update-index --chmod=+x pi/scripts/install-udev.sh
git commit -m "feat(pi): udev rule for non-root evdev access"
```

- [ ] **Step 4: Deploy and install**

```powershell
bash deploy/deploy.sh
ssh musi@musi.local "sudo /opt/musi/pi/scripts/install-udev.sh"
```

- [ ] **Step 5: Verify**

On the Pi:
```bash
ls -l /dev/input/event*
```

Expected: each device shows group `input` and permissions `crw-rw----`.

```bash
groups
```

Expected: `musi` is in `input`.

Re-run the hello app **without** sudo:
```bash
ssh musi@musi.local "cd /opt/musi && python3 -m musi hello"
```

Expected: app runs and accepts input as before.

---

## Task 13: Autostart hello on boot via systemd

**Files:**
- Create: `D:\project\musi\pi\systemd\musi-hello.service`

- [ ] **Step 1: Write the systemd unit**

`pi/systemd/musi-hello.service`:

```ini
[Unit]
Description=musi hello-world pygame app (Plan 01 placeholder)
After=fbcp.service systemd-user-sessions.service
Wants=fbcp.service
Conflicts=getty@tty1.service

[Service]
Type=simple
User=musi
Group=musi
SupplementaryGroups=input audio video gpio spi i2c
WorkingDirectory=/opt/musi
Environment=PYTHONPATH=/opt/musi/src
Environment=SDL_VIDEODRIVER=fbcon
Environment=SDL_FBDEV=/dev/fb0
Environment=SDL_AUDIODRIVER=alsa
ExecStart=/usr/bin/python3 -m musi hello
Restart=on-failure
RestartSec=2
StartLimitBurst=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Commit**

```powershell
git add pi/systemd/musi-hello.service
git commit -m "feat(pi): systemd unit for hello autostart"
```

- [ ] **Step 3: Deploy + install + enable**

```powershell
bash deploy/deploy.sh
ssh musi@musi.local "sudo cp /opt/musi/pi/systemd/musi-hello.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl disable getty@tty1.service && sudo systemctl enable musi-hello.service"
```

- [ ] **Step 4: Test by starting the service**

```bash
ssh musi@musi.local "sudo systemctl start musi-hello.service"
sleep 2
ssh musi@musi.local "sudo systemctl status musi-hello.service --no-pager"
```

Expected: `active (running)`. Display shows the hello screen.

- [ ] **Step 5: Test boot-to-display**

```bash
ssh musi@musi.local "sudo reboot"
```

Time the boot from power-on to the hello screen appearing on the display. Expected: <30 seconds (we'll tighten this in later plans).

- [ ] **Step 6: Verify it survived reboot**

After it boots:
```bash
ssh musi@musi.local "systemctl is-active musi-hello.service fbcp.service mpd.service"
```

Expected: all three `active`.

The display should be showing the hello screen with the orange dot. Pressing buttons should move the dot.

---

## Task 14: Hardware smoke-check script

**Files:**
- Create: `D:\project\musi\pi\scripts\verify-hw.sh`

- [ ] **Step 1: Write the script**

`pi/scripts/verify-hw.sh`:

```bash
#!/usr/bin/env bash
# Run a sequence of sanity checks against the hardware.
# Exits 0 if all pass, nonzero if any fail.
set -uo pipefail

fail=0
pass() { echo "  PASS: $1"; }
miss() { echo "  FAIL: $1"; fail=1; }

echo "=== musi hardware verification ==="

# SPI
[[ -e /dev/spidev0.0 ]] && pass "SPI0 CE0 present" || miss "SPI0 CE0 missing — display won't work"
[[ -e /dev/spidev0.1 ]] && pass "SPI0 CE1 present" || miss "SPI0 CE1 missing — touch won't work"

# I2C
[[ -e /dev/i2c-1 ]] && pass "I2C-1 present" || miss "I2C-1 missing"

# Audio card
if aplay -l 2>/dev/null | grep -q "hifiberry"; then
    pass "PCM5102A (hifiberry-dac) detected"
else
    miss "PCM5102A not detected — check I2S overlay + wiring"
fi

# Input devices
if cat /proc/bus/input/devices | grep -qi "ADS7846\|Touchscreen"; then
    pass "Touchscreen input device present"
else
    miss "Touchscreen input device missing — check ads7846 overlay + T_IRQ wiring"
fi

button_count=$(cat /proc/bus/input/devices | grep -ci "gpio-key")
if (( button_count >= 1 )); then
    pass "gpio-keys input(s) present ($button_count)"
else
    miss "No gpio-keys devices found — check button overlays"
fi

# Framebuffer + fbcp
[[ -e /dev/fb0 ]] && pass "/dev/fb0 present" || miss "/dev/fb0 missing"
if systemctl is-active fbcp.service >/dev/null 2>&1; then
    pass "fbcp.service running"
else
    miss "fbcp.service not running"
fi

# MPD
if systemctl is-active mpd.service >/dev/null 2>&1; then
    pass "mpd.service running"
else
    miss "mpd.service not running"
fi

if (( fail == 0 )); then
    echo
    echo "All hardware checks PASSED."
else
    echo
    echo "$fail hardware check(s) FAILED. See above."
fi
exit $fail
```

- [ ] **Step 2: Commit**

```powershell
git add pi/scripts/verify-hw.sh
git update-index --chmod=+x pi/scripts/verify-hw.sh
git commit -m "feat(pi): hardware verification smoke-check script"
```

- [ ] **Step 3: Run it on the Pi**

```powershell
bash deploy/deploy.sh
ssh musi@musi.local "bash /opt/musi/pi/scripts/verify-hw.sh"
```

Expected: all PASS lines, exit code 0.

---

## Task 15: Tag v0.1 and wrap up

- [ ] **Step 1: Verify the working state one more time**

On the Pi, with the device on the bench:
- Display shows the hello screen
- Buttons move the dot
- Touch updates the input label
- MPD plays a track when triggered (`mpc play`)

- [ ] **Step 2: Update README with the achieved state**

`README.md` (append below the quickstart):

```markdown
## Status

**v0.1 — System foundation complete.**

- Pi Zero 2 W boots Raspberry Pi OS Lite Bookworm 64-bit
- 2.8" SPI TFT display drives via fbcp-ili9341 (DMA, ~30+ FPS)
- 8 buttons + 1 power button + XPT2046 touch wired and producing evdev events
- PCM5102A I2S DAC plays audio via MPD
- pygame hello-world app autostarts on boot
- Deploy is `bash deploy/deploy.sh` from the dev machine

Next: Plan 02 — library indexer and SQLite schema.
```

- [ ] **Step 3: Commit and tag**

```powershell
git add README.md
git commit -m "docs: v0.1 — system foundation complete"
git tag v0.1
```

- [ ] **Step 4: Push to a remote (if you have one)**

If you have a git remote configured:
```powershell
git push origin main
git push origin v0.1
```

Otherwise, the local tag is fine for now.

---

## Definition of done for Plan 01

✅ Pi boots Raspberry Pi OS Lite Bookworm 64-bit on first try
✅ Display is alive and shows pygame output via fbcp-ili9341
✅ All 9 user buttons + power button produce evdev events
✅ Touch produces evdev ABS events
✅ PCM5102A DAC plays an MPD-triggered test track
✅ Hello pygame app autostarts on boot via systemd
✅ Deploy script syncs dev machine → Pi over Wi-Fi
✅ Hardware verification script passes all checks
✅ Tests pass on dev machine: `python -m pytest -v`
✅ Repo tagged v0.1

You now have a working "device shell" — every hardware subsystem is verified and accessible from Python. Plan 02 (Library indexer + SQLite) starts implementing the real application on top of this foundation.
