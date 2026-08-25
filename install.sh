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

# bluez stability policy: adapter on at boot, fast reconnect window, and
# bluez's own link-loss reconnect for trusted audio devices. The stock
# main.conf ships these commented out — uncomment-and-set is idempotent
# (a re-run matches nothing once the lines are live).
BT_MAIN=/etc/bluetooth/main.conf
if [ -f "$BT_MAIN" ]; then
    sudo sed -i \
        -e 's/^#[[:space:]]*FastConnectable[[:space:]]*=.*/FastConnectable = true/' \
        -e 's/^#[[:space:]]*AutoEnable[[:space:]]*=.*/AutoEnable=true/' \
        -e 's/^#[[:space:]]*ReconnectAttempts[[:space:]]*=.*/ReconnectAttempts=5/' \
        -e 's/^#[[:space:]]*ReconnectIntervals[[:space:]]*=.*/ReconnectIntervals=1,2,4,8,16/' \
        "$BT_MAIN"
    sudo systemctl restart bluetooth 2>/dev/null || true
fi
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
echo "  IMPORTANT: 'fbcon=map:10' is NOT just cosmetic. It maps the console onto"
echo "        the SPI panel, which is what enables the DRM pipeline at boot. On a"
echo "        clean Raspberry Pi OS install with nothing else driving the panel,"
echo "        writes to /dev/fb1 land in a buffer that is never scanned out and"
echo "        the screen stays dark even though the driver loaded without error."

# ── 9b. backlight permissions (screen dim/off) ────────────────────────────────
say "[9b] Backlight write access for screen auto-off"
# The panel overlay (backlight-gpio=12) exposes a gpio-backlight device; let the
# app (video group) switch it off after inactivity. Rule applies on every boot.
sudo tee /etc/udev/rules.d/90-musi-backlight.rules > /dev/null <<'EOF'
SUBSYSTEM=="backlight", ACTION=="add", RUN+="/bin/sh -c 'chgrp video /sys/class/backlight/%k/brightness && chmod g+w /sys/class/backlight/%k/brightness'"
EOF
sudo udevadm control --reload-rules 2>/dev/null || true
# also apply to devices already present this boot
for b in /sys/class/backlight/*/brightness; do
    [ -e "$b" ] && sudo chgrp video "$b" && sudo chmod g+w "$b"
done

# ── 9c. power controls (Settings → Power) ─────────────────────────────────────
say "[9c] Power-off / reboot permission"

# The root half of update.sh runs from a ROOT-OWNED copy, never from the git
# checkout. The checkout is writable by this user, so granting sudo on a script
# in it would let anyone with code execution as this user append a line and
# become root — i.e. it would be equivalent to NOPASSWD: ALL.
#
# Consequence, by design: OTA can update the user half freely, but changing what
# runs as root requires re-running this installer (which asks for a real sudo
# password). update.sh detects a stale copy and tells you.
sudo install -d -m 0755 -o root -g root /usr/local/lib/musi
sudo install -m 0755 -o root -g root "$SCRIPT_DIR/update.sh" /usr/local/lib/musi/update-root.sh

# Sudoers rules must be a single line; a malformed sudoers.d file makes every
# sudo call print parse errors. Validate with visudo before installing.
#
# Each entry is the narrowest form the app actually invokes. Commas inside an
# argument must be backslash-escaped or sudoers reads them as rule separators.
TMP_SUDOERS="$(mktemp)"
printf '%s ALL=(root) NOPASSWD: %s\n' "$USER_NAME" \
"/usr/bin/systemctl poweroff, \
/usr/bin/systemctl poweroff -i, \
/usr/bin/systemctl reboot, \
/usr/bin/systemctl reboot -i, \
/usr/bin/nmcli -t -f IN-USE\\,SIGNAL\\,SECURITY\\,SSID device wifi list --rescan yes, \
/usr/bin/nmcli device wifi connect *, \
/usr/bin/nmcli connection delete id *, \
/usr/sbin/iw dev wlan0 set power_save on, \
/usr/sbin/iw dev wlan0 set power_save off, \
/usr/bin/raspi-config nonint do_overlayfs 0, \
/usr/bin/raspi-config nonint do_overlayfs 1, \
/bin/bash /usr/local/lib/musi/update-root.sh --root *" > "$TMP_SUDOERS"
if sudo visudo -c -f "$TMP_SUDOERS" > /dev/null; then
    sudo install -m 0440 -o root -g root "$TMP_SUDOERS" /etc/sudoers.d/musi-power
else
    echo "  !! sudoers rule failed visudo validation — removing; Power screen won't work"
    sudo rm -f /etc/sudoers.d/musi-power
fi
rm -f "$TMP_SUDOERS"

# ── 9d. OS hardening (SD-card protection + battery) ──────────────────────────
say "[9d] OS hardening"
# No swap: a swapfile is pure SD wear on a 512MB Zero W and useless for this app.
sudo systemctl disable --now dphys-swapfile 2>/dev/null || true
sudo dphys-swapfile swapoff 2>/dev/null || true
sudo dphys-swapfile uninstall 2>/dev/null || true

# Journal in RAM only — logs don't survive reboot, but nothing writes the card.
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/musi.conf > /dev/null <<'EOF'
[Journal]
Storage=volatile
RuntimeMaxUse=16M
EOF
sudo systemctl restart systemd-journald 2>/dev/null || true

# /tmp in RAM.
if ! grep -qE '^\s*tmpfs\s+/tmp\s' /etc/fstab; then
    echo 'tmpfs /tmp tmpfs mode=1777,nosuid,nodev,size=64m 0 0' | sudo tee -a /etc/fstab > /dev/null
fi

# Faster boot: skip the firmware's 1s pause and the rainbow GPU splash.
BOOT_CFG=/boot/firmware/config.txt
[ -f "$BOOT_CFG" ] || BOOT_CFG=/boot/config.txt
for kv in boot_delay=0 disable_splash=1; do
    grep -q "^${kv%%=*}=" "$BOOT_CFG" || echo "$kv" | sudo tee -a "$BOOT_CFG" > /dev/null
done

# Wi-Fi power save on by default (the app turns it off while WiFi Transfer is
# open — power save adds latency that slows uploads).
sudo mkdir -p /etc/NetworkManager/conf.d
sudo tee /etc/NetworkManager/conf.d/musi-wifi-powersave.conf > /dev/null <<'EOF'
[connection]
# 3 = enable, 2 = disable
wifi.powersave = 3
EOF
sudo systemctl reload NetworkManager 2>/dev/null || true

# NOTE: the storage lock (read-only overlay root) is NOT enabled here — it is
# toggled from Settings -> Power on the device (raspi-config nonint
# do_overlayfs, allowed via the sudoers rule above) and applies after reboot.

# ── 10. services + autostart ──────────────────────────────────────────────────
say "[10/10] Enabling services + autostart"
install -m 0644 "$SCRIPT_DIR/pi/musi-ui.service" "$HOME/.config/systemd/user/musi-ui.service"
install -m 0644 "$SCRIPT_DIR/pi/musi-api.service" "$HOME/.config/systemd/user/musi-api.service"
loginctl enable-linger "$USER_NAME" 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable mpd musi-bt-router mpris-proxy musi-ui musi-api 2>/dev/null || true
sudo hostnamectl set-hostname musi 2>/dev/null || true
sudo systemctl enable --now avahi-daemon 2>/dev/null || true

# Seed the incremental-update level: a full install covers everything
# update.sh knows about, so OTA updates only apply steps added later.
UPDATE_LEVEL="$(sed -n 's/^LATEST_STEP=\([0-9]*\)$/\1/p' "$SCRIPT_DIR/update.sh" | head -1)"
mkdir -p "$HOME/.local/share/musi"
echo "${UPDATE_LEVEL:-0}" > "$HOME/.local/share/musi/update-level"

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
