#!/bin/bash
# musi install script for Raspberry Pi
# Run from the project directory: bash install.sh
# Tested on Raspberry Pi OS Bookworm (64-bit), Pi Zero 2 W / Pi 3 / Pi 4

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MUSIC_DIR="$HOME/Music"
DATA_DIR="$HOME/.local/share/musi"
MPD_PLAYLIST_DIR="$HOME/.mpd/playlists"

echo "=== musi installer ==="
echo "Project: $SCRIPT_DIR"
echo "Music:   $MUSIC_DIR"
echo ""

# ── 1. system packages ────────────────────────────────────────────────────────
echo "[1/7] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y \
    mpd \
    python3 python3-pip python3-venv \
    fonts-dejavu-core \
    libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev \
    avahi-daemon \
    libjpeg-dev libpng-dev \
    network-manager \
    --no-install-recommends

# ── 2. Python virtual environment ─────────────────────────────────────────────
echo "[2/7] Creating Python virtual environment..."
python3 -m venv "$SCRIPT_DIR/.venv" --system-site-packages
"$SCRIPT_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$SCRIPT_DIR/.venv/bin/pip" install --quiet -e "$SCRIPT_DIR[dev]"

# ── 3. directories ────────────────────────────────────────────────────────────
echo "[3/7] Creating directories..."
mkdir -p "$MUSIC_DIR"
mkdir -p "$DATA_DIR"
mkdir -p "$MPD_PLAYLIST_DIR"

# ── 4. MPD configuration ──────────────────────────────────────────────────────
echo "[4/7] Configuring MPD..."

# Stop system MPD first so we can replace its config
sudo systemctl stop mpd 2>/dev/null || true

# Write MPD config (substituting actual home dir)
sudo tee /etc/mpd.conf > /dev/null << EOF
music_directory     "$MUSIC_DIR"
playlist_directory  "$MPD_PLAYLIST_DIR"
db_file             "$DATA_DIR/mpd.db"
log_file            "$DATA_DIR/mpd.log"
state_file          "$DATA_DIR/mpd.state"
sticker_database    "$DATA_DIR/mpd.sticker.db"

bind_to_address     "127.0.0.1"
port                "6600"

user                "pi"
group               "audio"

auto_update         "yes"
auto_update_depth   "3"

replaygain          "auto"

audio_output {
    type        "alsa"
    name        "PCM5102A DAC"
    device      "hw:0,0"
    mixer_type  "software"
}
EOF

# Make pi user a member of audio group
sudo usermod -aG audio pi 2>/dev/null || true
sudo usermod -aG video pi 2>/dev/null || true

# ── 5. systemd service ────────────────────────────────────────────────────────
echo "[5/7] Installing systemd service..."

sudo tee /etc/systemd/system/musi.service > /dev/null << EOF
[Unit]
Description=musi player UI
After=network.target mpd.service sound.target
Wants=mpd.service

[Service]
User=pi
Group=video
WorkingDirectory=$SCRIPT_DIR
Environment=SDL_VIDEODRIVER=kmsdrm
Environment=SDL_RENDER_DRIVER=software
Environment=SDL_MOUSE_RELATIVE=0
Environment=MUSI_MUSIC_ROOT=$MUSIC_DIR
ExecStart=$SCRIPT_DIR/.venv/bin/python -m musi.player
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=musi

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable mpd
sudo systemctl start  mpd
sudo systemctl enable musi

# ── 6. mDNS hostname (musi.local) ────────────────────────────────────────────
echo "[6/7] Configuring mDNS..."
sudo hostnamectl set-hostname musi 2>/dev/null || true
sudo systemctl enable avahi-daemon
sudo systemctl start  avahi-daemon

# ── 7. display driver reminder ────────────────────────────────────────────────
echo "[7/7] Display setup..."
cat << 'DISPLAY_NOTE'

  ┌─────────────────────────────────────────────────────────────┐
  │  DISPLAY DRIVER — manual step required                      │
  │                                                             │
  │  Add the following to /boot/firmware/config.txt             │
  │  (or /boot/config.txt on older Pi OS):                      │
  │                                                             │
  │    dtparam=spi=on                                           │
  │    dtparam=i2s=on                                           │
  │    dtoverlay=hifiberry-dac          # PCM5102A audio        │
  │                                                             │
  │  For the ST7796 / ILI9488 3.5" SPI display, use your       │
  │  display vendor's driver.  Common options:                  │
  │                                                             │
  │  Option A — fbcp-ili9341 (recommended for SPI displays):    │
  │    https://github.com/juj/fbcp-ili9341                      │
  │    Then change SDL_VIDEODRIVER=fbcon in musi.service        │
  │    and set SDL_FBDEV=/dev/fb1                               │
  │                                                             │
  │  Option B — waveshare/goodtft driver (if your display       │
  │    came with a driver package, run their install script)    │
  │                                                             │
  │  Option C — DRM overlay (if your display supports it):      │
  │    dtoverlay=vc4-kms-v3d                                    │
  │    + your display's kms overlay                             │
  │                                                             │
  │  After editing config.txt, run: sudo reboot                 │
  └─────────────────────────────────────────────────────────────┘

DISPLAY_NOTE

# ── done ──────────────────────────────────────────────────────────────────────
echo ""
echo "=== Installation complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit /boot/firmware/config.txt for your display + audio (see above)"
echo "  2. sudo reboot"
echo "  3. After reboot, scan your music library:"
echo "       cd $SCRIPT_DIR && .venv/bin/python -m musi.library"
echo "  4. Start the player manually to test:"
echo "       bash $SCRIPT_DIR/run.sh"
echo "  5. Once working, the service auto-starts on every boot."
echo ""
echo "  Logs:    sudo journalctl -u musi -f"
echo "  MPD:     sudo journalctl -u mpd -f"
echo "  Re-scan: .venv/bin/python -m musi.library"
echo ""
