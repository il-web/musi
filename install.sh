#!/bin/bash
# musi OS installer — software setup for the touchscreen music player.
#
# Run from a checkout on the Pi:   cd ~/musi && bash install.sh
#
# This configures the SOFTWARE stack: MPD, the player app, audio routing
# (DAC + Bluetooth via bluez-alsa), Bluetooth pairing agent + AVRCP, the boot
# splash, and the auto-start service.
#
# PREREQUISITES (hardware enablement — do these first, see README §2–3):
#   - SPI display wired + /boot/firmware/config.txt overlays + /lib/firmware/panel.bin
#   - I2C touch overlay installed
#   - I2S DAC wired (optional)
#
# Idempotent: safe to re-run. Assembled from the verified per-step setup;
# this clean-install path is new — please report issues.
set -u

USER_NAME="$(id -un)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MUSIC_DIR="$HOME/music"

say() { printf '\n\033[1;35m=== %s\033[0m\n' "$1"; }

# ── 1. packages ───────────────────────────────────────────────────────────────
say "[1/10] Installing packages"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    git mpd mpc \
    python3 python3-pip python3-venv \
    fonts-dejavu-core \
    libsdl2-2.0-0 libsdl2-image-2.0-0 libsdl2-ttf-2.0-0 libsdl2-mixer-2.0-0 \
    bluez bluez-tools bluez-alsa-utils \
    plymouth plymouth-themes \
    i2c-tools device-tree-compiler \
    avahi-daemon

# ── 2. python app ─────────────────────────────────────────────────────────────
say "[2/10] Python virtual environment"
python3 -m venv "$SCRIPT_DIR/.venv" --system-site-packages
"$SCRIPT_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$SCRIPT_DIR/.venv/bin/pip" install --quiet -e "$SCRIPT_DIR"

# ── 3. groups + radios ────────────────────────────────────────────────────────
say "[3/10] User groups and Bluetooth radio"
for g in audio video render input bluetooth gpio i2c spi netdev; do
    sudo usermod -aG "$g" "$USER_NAME" 2>/dev/null || true
done
sudo rfkill unblock bluetooth 2>/dev/null || true
sudo systemctl enable --now bluetooth 2>/dev/null || true

# ── 4. directories ────────────────────────────────────────────────────────────
say "[4/10] Directories"
mkdir -p "$MUSIC_DIR" "$HOME/.config/mpd/playlists" "$HOME/.local/bin" \
         "$HOME/.config/systemd/user"

# ── 5. MPD as a user service ──────────────────────────────────────────────────
say "[5/10] MPD (user service, output via switchable ALSA device)"
sudo systemctl mask mpd.service mpd.socket 2>/dev/null || true
cat > "$HOME/.config/mpd/mpd.conf" <<EOF
music_directory     "$MUSIC_DIR"
playlist_directory  "$HOME/.config/mpd/playlists"
db_file             "$HOME/.config/mpd/database"
state_file          "$HOME/.config/mpd/state"
sticker_file        "$HOME/.config/mpd/sticker.sql"
bind_to_address     "127.0.0.1"
port                "6600"
auto_update         "yes"
restore_paused      "yes"
audio_output {
    type        "alsa"
    name        "musi out"
    device      "musiout"
    mixer_type  "software"
}
EOF
# Default audio route → the DAC, referenced by stable card NAME (the ALSA index
# is not stable across boots — HDMI can claim card 0).
DAC_ID="$(aplay -l 2>/dev/null | sed -n 's/^card [0-9]*: \([^ ]*\).*[Hh]ifi[Bb]erry.*/\1/p' | head -1)"
[ -z "$DAC_ID" ] && DAC_ID="sndrpihifiberry"
cat > "$HOME/.asoundrc" <<EOF
pcm.musiout {
    type plug
    slave.pcm "hw:$DAC_ID,0"
}
EOF

# ── 6. Bluetooth audio (bluez-alsa) ───────────────────────────────────────────
say "[6/10] Bluetooth audio (bluez-alsa) + pairing agent"
sudo systemctl enable --now bluealsa 2>/dev/null || true
# Persistent auto-accept pairing agent (so the app can pair new devices).
sudo tee /etc/systemd/system/bt-agent.service > /dev/null <<EOF
[Unit]
Description=Bluetooth auto-pairing agent
After=bluetooth.service
Requires=bluetooth.service
[Service]
ExecStartPre=/bin/sleep 2
ExecStart=/usr/bin/bt-agent --capability=NoInputNoOutput
Restart=always
RestartSec=3
[Install]
WantedBy=bluetooth.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now bt-agent 2>/dev/null || true

# ── 7. audio auto-router (DAC <-> Bluetooth) ──────────────────────────────────
say "[7/10] Audio auto-router"
install -m 0755 "$SCRIPT_DIR/pi/musi-bt-router" "$HOME/.local/bin/musi-bt-router"
sed -i 's/\r$//' "$HOME/.local/bin/musi-bt-router"
cat > "$HOME/.config/systemd/user/musi-bt-router.service" <<EOF
[Unit]
Description=musi Bluetooth/DAC audio auto-router
After=bluetooth.service mpd.service
[Service]
ExecStart=/bin/bash %h/.local/bin/musi-bt-router
Restart=always
RestartSec=3
[Install]
WantedBy=default.target
EOF

# ── 8. AVRCP (headphone media buttons -> MPD) ─────────────────────────────────
say "[8/10] AVRCP media-button control"
sudo apt-get install -y --no-install-recommends mpdris2 2>/dev/null || true
cat > "$HOME/.config/systemd/user/mpris-proxy.service" <<EOF
[Unit]
Description=Bluetooth AVRCP to MPRIS proxy
After=bluetooth.service
[Service]
ExecStart=/usr/bin/mpris-proxy
Restart=always
RestartSec=3
[Install]
WantedBy=default.target
EOF

# ── 9. boot splash (Plymouth) ─────────────────────────────────────────────────
say "[9/10] Boot splash"
sudo mkdir -p /usr/share/plymouth/themes/musi
sudo cp "$SCRIPT_DIR"/pi/plymouth-text/* /usr/share/plymouth/themes/musi/
sudo cp "$SCRIPT_DIR/pi/initramfs-hook-panel" /etc/initramfs-tools/hooks/panel-firmware
sudo sed -i 's/\r$//' /etc/initramfs-tools/hooks/panel-firmware
sudo chmod +x /etc/initramfs-tools/hooks/panel-firmware
echo 'export FRAMEBUFFER=/dev/fb1' | sudo tee /etc/initramfs-tools/conf.d/fb1 > /dev/null
grep -q '^panel-mipi-dbi' /etc/initramfs-tools/modules 2>/dev/null || \
    printf 'spi-bcm2835\npanel-mipi-dbi\nmipi-dbi\n' | sudo tee -a /etc/initramfs-tools/modules > /dev/null
sudo sed -i 's/^MODULES=.*/MODULES=most/' /etc/initramfs-tools/initramfs.conf 2>/dev/null || true
sudo plymouth-set-default-theme musi 2>/dev/null || true
sudo update-initramfs -u 2>/dev/null || true
echo "  NOTE: add 'quiet splash plymouth.ignore-serial-consoles fbcon=map:10' to"
echo "        /boot/firmware/cmdline.txt (one line) for the splash at boot."

# ── 9b. power controls (Settings → Power) ─────────────────────────────────────
say "[9b] Power-off / reboot permission"
echo "$USER_NAME ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff, /usr/bin/systemctl poweroff -i, /usr/bin/systemctl reboot, /usr/bin/systemctl reboot -i" \
    | sudo tee /etc/sudoers.d/musi-power > /dev/null
sudo chmod 0440 /etc/sudoers.d/musi-power

# ── 10. services + autostart ──────────────────────────────────────────────────
say "[10/10] Enabling services + autostart"
install -m 0644 "$SCRIPT_DIR/pi/musi-ui.service" "$HOME/.config/systemd/user/musi-ui.service"
loginctl enable-linger "$USER_NAME" 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable mpd musi-bt-router mpris-proxy musi-ui 2>/dev/null || true
sudo hostnamectl set-hostname musi 2>/dev/null || true
sudo systemctl enable --now avahi-daemon 2>/dev/null || true

say "Done"
cat <<EOF

  musi OS software is installed.

  1. Make sure the display/touch/DAC are enabled in /boot/firmware/config.txt
     and add the cmdline.txt splash params noted above (README §3).
  2. Put music in $MUSIC_DIR  (or use Wi-Fi transfer once running).
  3. Reboot:   sudo reboot

  The Pi will boot straight into musi OS.
  Logs:  journalctl --user -u musi-ui -f
EOF
