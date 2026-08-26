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

# `systemctl --user` needs the user bus. Over a bare `ssh host 'bash install.sh'`
# neither XDG_RUNTIME_DIR nor DBUS_SESSION_BUS_ADDRESS is set, and every user-unit
# call dies with "Failed to connect to user scope bus via local transport".
# Set them ourselves so the install works from any kind of shell.
: "${XDG_RUNTIME_DIR:=/run/user/$(id -u)}"
export XDG_RUNTIME_DIR
: "${DBUS_SESSION_BUS_ADDRESS:=unix:path=$XDG_RUNTIME_DIR/bus}"
export DBUS_SESSION_BUS_ADDRESS

# ── presentation ──────────────────────────────────────────────────────────────
if [ -t 1 ] && [ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]; then
    C_ACCENT=$'\033[38;5;170m'; C_DIM=$'\033[2m'; C_OK=$'\033[38;5;114m'
    C_WARN=$'\033[38;5;215m'; C_BOLD=$'\033[1m'; C_OFF=$'\033[0m'
else
    C_ACCENT=; C_DIM=; C_OK=; C_WARN=; C_BOLD=; C_OFF=
fi

TOTAL_STEPS=10
STEP_N=0

banner() {
    printf '\n%s' "$C_ACCENT"
    cat <<'ART'
    ██   ██  ██   ██   ██████   ██
    ███ ███  ██   ██  ██        ██
    ██ █ ██  ██   ██   █████    ██
    ██   ██  ██   ██       ██   ██
    ██   ██   █████   ██████    ██
ART
    printf '%s%s              a touchscreen music player%s\n\n' "$C_OFF" "$C_DIM" "$C_OFF"
}

# say "Title"            -> numbered step, auto-incrementing
# say "Title" "9b"       -> explicit label for sub-steps
say() {
    if [ $# -ge 2 ]; then
        label="$2"
    else
        STEP_N=$((STEP_N + 1))
        label="$STEP_N/$TOTAL_STEPS"
    fi
    printf '\n%s%s┌─ %s %s%s\n' "$C_BOLD" "$C_ACCENT" "[$label]" "$1" "$C_OFF"
}
ok()   { printf '   %s✓%s %s\n' "$C_OK" "$C_OFF" "$1"; }
info() { printf '   %s·%s %s\n' "$C_DIM" "$C_OFF" "$1"; }
warn() { printf '   %s!%s %s%s%s\n' "$C_WARN" "$C_OFF" "$C_WARN" "$1" "$C_OFF"; }

banner

# ── 1. packages ───────────────────────────────────────────────────────────────
say "Installing packages"
sudo apt-get update -qq
# libgl1-mesa-dri / libegl1 / libgbm1 / libgles2 are NOT optional, and are easy
# to miss: Raspberry Pi OS Lite 64-bit ships none of them. SDL2's KMSDRM backend
# needs EGL+GBM, and a display-only SPI panel needs Mesa's kmsro driver
# (panel-mipi-dbi_dri.so) to borrow the VideoCore render node.
#
# libgles2 is the one that hides: SDL_EGL_LoadLibrary() dlopens libEGL AND
# libGLESv2, and if the GLESv2 load fails every later call reports the generic
# "pygame.error: EGL not initialized" -- pointing at EGL, which is fine. A direct
# eglInitialize() on the same device succeeds, because it never touches GLESv2.
# Meanwhile every other check -- driver bound, framebuffer present, correct pin
# muxing, no dmesg errors -- looks perfect.
#
# The 32-bit image happened to include all of these, so this only bites on arm64.
sudo apt-get install -y --no-install-recommends \
    git mpd mpc \
    python3 python3-pip python3-venv \
    fonts-dejavu-core \
    libsdl2-2.0-0 libsdl2-image-2.0-0 libsdl2-ttf-2.0-0 libsdl2-mixer-2.0-0 \
    libgl1-mesa-dri libegl1 libgbm1 libgles2 \
    bluez bluez-tools bluez-alsa-utils \
    plymouth plymouth-themes \
    i2c-tools device-tree-compiler \
    avahi-daemon
ok "packages installed"

# Sanity-check the graphics stack now rather than at first boot.
DRI_DIR="/usr/lib/$(dpkg-architecture -qDEB_HOST_MULTIARCH 2>/dev/null || echo "$(uname -m)-linux-gnu")/dri"
if [ -e "$DRI_DIR/panel-mipi-dbi_dri.so" ]; then
    ok "Mesa kmsro driver present (SPI panel can get EGL)"
else
    warn "panel-mipi-dbi_dri.so not found in $DRI_DIR"
    warn "an SPI panel UI may fail with 'EGL not initialized'"
fi

# ── 2. python app ─────────────────────────────────────────────────────────────
say "Python virtual environment"
python3 -m venv "$SCRIPT_DIR/.venv" --system-site-packages
"$SCRIPT_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$SCRIPT_DIR/.venv/bin/pip" install --quiet -e "$SCRIPT_DIR"

# ── 3. groups + radios ────────────────────────────────────────────────────────
say "User groups and Bluetooth radio"
for g in audio video render input bluetooth gpio i2c spi netdev; do
    sudo usermod -aG "$g" "$USER_NAME" 2>/dev/null || true
done
sudo rfkill unblock bluetooth 2>/dev/null || true
sudo systemctl enable --now bluetooth 2>/dev/null || true

# ── 4. directories ────────────────────────────────────────────────────────────
say "Directories"
mkdir -p "$MUSIC_DIR" "$HOME/.config/mpd/playlists" "$HOME/.local/bin" \
         "$HOME/.config/systemd/user"

# ── 5. MPD as a user service ──────────────────────────────────────────────────
say "MPD (user service, output via switchable ALSA device)"
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
say "Bluetooth audio (bluez-alsa) + pairing agent"
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
say "Audio auto-router"
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
say "AVRCP media-button control"
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
say "Boot splash"
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
say "Backlight write access for screen auto-off" "9b"
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
say "Power-off / reboot permission" "9c"

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
say "OS hardening" "9d"
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

# Power: mirrors update.sh root_5 — keep the two in step (tests enforce it).
# The ACT (green) and PWR (red) LEDs are pointless inside a sealed case and leak
# light into it; HDMI is never plugged in. Both are pure boot-time settings.
# Match the WHOLE line here: "^dtparam=" would hit the i2s and panel params
# already in the file and skip every one of these.
for line in \
    'dtparam=act_led_trigger=none' \
    'dtparam=act_led_activelow=off' \
    'dtparam=pwr_led_trigger=none' \
    'dtparam=pwr_led_activelow=off'
do
    grep -qxF "$line" "$BOOT_CFG" || echo "$line" | sudo tee -a "$BOOT_CFG" > /dev/null
done

# HDMI off. "tvservice -o" does NOT work under KMS/DRM — that is the legacy
# firmware path. Disabling the connector on the kernel command line is the
# equivalent that does. cmdline.txt is ONE line: append to it, never add one.
BOOT_CMDLINE=/boot/firmware/cmdline.txt
[ -f "$BOOT_CMDLINE" ] || BOOT_CMDLINE=/boot/cmdline.txt
if [ -f "$BOOT_CMDLINE" ] && ! grep -q 'video=HDMI-A-1:d' "$BOOT_CMDLINE"; then
    sudo sed -i -e '1s/[[:space:]]*$//' -e '1s/$/ video=HDMI-A-1:d/' "$BOOT_CMDLINE"
fi
# NOTE: with no LEDs and no console, a panel that fails to come up leaves no
# local sign of life — SSH is the way back in. That is part of why the Pi 3's
# Ethernet/USB hub is deliberately left powered.

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
say "Enabling services + autostart"
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

# ── final health check ────────────────────────────────────────────────────────
say "Health check" "✓"
if [ -e /dev/fb0 ] || [ -e /dev/fb1 ]; then
    ok "framebuffer present"
else
    warn "no framebuffer — check the display overlay in config.txt"
fi

if [ -e "$DRI_DIR/panel-mipi-dbi_dri.so" ]; then
    ok "Mesa kmsro driver"
else
    warn "Mesa kmsro driver MISSING — UI will not start on an SPI panel"
fi

if [ -d /sys/bus/i2c/devices/1-0038 ]; then
    ok "touch controller answering at 0x38"
else
    info "no touch at 0x38 (fine if you have no touch panel)"
fi

if aplay -l 2>/dev/null | grep -qi hifiberry; then
    ok "I2S DAC card present"
else
    info "no hifiberry card (Bluetooth-only output is fine)"
fi

if grep -q "fbcon=map:10" /boot/firmware/cmdline.txt 2>/dev/null; then
    ok "fbcon=map:10 set (SPI panel gets a DRM modeset at boot)"
else
    warn "fbcon=map:10 MISSING from cmdline.txt — an SPI panel will stay dark"
fi

if systemctl --user is-enabled musi-ui >/dev/null 2>&1; then
    ok "musi-ui enabled at boot"
else
    warn "musi-ui not enabled — autostart will not work"
fi

printf '\n%s%s' "$C_BOLD" "$C_ACCENT"
cat <<'ART'
   ┌──────────────────────────────────────────────┐
   │   musi OS is installed                       │
   └──────────────────────────────────────────────┘
ART
printf '%s' "$C_OFF"
cat <<EOF
   ${C_BOLD}1.${C_OFF} Hardware must be enabled in /boot/firmware/config.txt, and
      cmdline.txt needs ${C_BOLD}fbcon=map:10${C_OFF} (see README §3).
   ${C_BOLD}2.${C_OFF} Put music in ${C_BOLD}$MUSIC_DIR${C_OFF}, or use Wi-Fi transfer once running.
   ${C_BOLD}3.${C_OFF} Reboot:  ${C_BOLD}sudo reboot${C_OFF}

   ${C_DIM}The Pi boots straight into musi OS.
   Logs:   journalctl --user -u musi-ui -f
   Status: systemctl --user status musi-ui${C_OFF}

EOF
