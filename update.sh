#!/usr/bin/env bash
# musi incremental updater — fast config sync after an OTA code update.
#
# Settings -> Updates runs this automatically after git pull (see
# src/musi/player/updater.py). It applies only the numbered steps this
# device hasn't run yet (state: ~/.local/share/musi/update-level), so it
# finishes in seconds — unlike install.sh, which reinstalls the whole
# stack and is only needed for first-time setup.
#
# ADDING A STEP FOR A NEW PACK:
#   1. bump LATEST_STEP
#   2. add user_N() and/or root_N() with only that pack's config changes
#   3. mirror the same change in install.sh for fresh installs
#      (install.sh seeds update-level to LATEST_STEP, so a fresh install
#       never re-runs steps it already covers)
#
# Root parts run through "sudo -n /bin/bash update.sh --root <level>";
# install.sh grants exactly that command passwordless (sudoers.d/musi-power).
set -u

SELF="$(readlink -f "$0")"
REPO="$(cd "$(dirname "$SELF")" && pwd)"
STATE_DIR="$HOME/.local/share/musi"
STATE="$STATE_DIR/update-level"

LATEST_STEP=3

# Pinned cloudflared for the remote tunnel. MUST be the generic ARM build:
# armhf/ARMv7 builds die with "illegal instruction" on the Zero W's ARMv6
# (cloudflared issue #1136). Bump deliberately after testing on-device.
CLOUDFLARED_VERSION="2026.6.1"

say() { printf '[update] %s\n' "$*"; }

# ══ steps ══════════════════════════════════════════════════════════════════════
# user_N runs as the normal user ($HOME files, user services).
# root_N runs as root via the single sudo call below. Both must be idempotent.

# ── step 1: BT stability pack (2026-07-04) ────────────────────────────────────
user_1() {
    install -m 0755 "$REPO/pi/musi-bt-router" "$HOME/.local/bin/musi-bt-router"
    sed -i 's/\r$//' "$HOME/.local/bin/musi-bt-router"
    systemctl --user restart musi-bt-router 2>/dev/null || true
}

root_1() {
    BT_MAIN=/etc/bluetooth/main.conf
    if [ -f "$BT_MAIN" ]; then
        sed -i \
            -e 's/^#[[:space:]]*FastConnectable[[:space:]]*=.*/FastConnectable = true/' \
            -e 's/^#[[:space:]]*AutoEnable[[:space:]]*=.*/AutoEnable=true/' \
            -e 's/^#[[:space:]]*ReconnectAttempts[[:space:]]*=.*/ReconnectAttempts=5/' \
            -e 's/^#[[:space:]]*ReconnectIntervals[[:space:]]*=.*/ReconnectIntervals=1,2,4,8,16/' \
            "$BT_MAIN"
        systemctl restart bluetooth 2>/dev/null || true
    fi
}

# ── step 2: Device API pack (2026-07-06) ─────────────────────────────────────
user_2() {
    install -m 0644 "$REPO/pi/musi-api.service" "$HOME/.config/systemd/user/musi-api.service"
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable --now musi-api 2>/dev/null || true
    systemctl --user restart musi-api 2>/dev/null || true
}

# ── step 3: Device API pack 3 — cloudflared binary (2026-07-07) ───────────────
root_3() {
    BIN=/usr/local/bin/cloudflared
    if [ -x "$BIN" ] && "$BIN" --version 2>/dev/null | grep -q "$CLOUDFLARED_VERSION"; then
        return 0
    fi
    URL="https://github.com/cloudflare/cloudflared/releases/download/$CLOUDFLARED_VERSION/cloudflared-linux-arm"
    if curl -fsSL --retry 2 -o "$BIN.tmp" "$URL"; then
        install -m 0755 "$BIN.tmp" "$BIN"
        rm -f "$BIN.tmp"
        say "cloudflared $CLOUDFLARED_VERSION installed"
    else
        rm -f "$BIN.tmp"
        say "!! cloudflared download failed (offline?) — tunnel setup can"
        say "   install it later, see docs/tunnel-setup.md"
    fi
}

# ══ mechanics ══════════════════════════════════════════════════════════════════

# Root phase: "update.sh --root <applied-level>" — runs root_N for the range.
if [ "${1:-}" = "--root" ]; then
    if [ "$(id -u)" != 0 ]; then
        echo "--root must run under sudo" >&2
        exit 1
    fi
    from="${2:-0}"
    case "$from" in (*[!0-9]*|'') from=0 ;; esac
    for n in $(seq $((from + 1)) "$LATEST_STEP"); do
        if declare -F "root_$n" > /dev/null; then
            say "root step $n"
            "root_$n"
        fi
    done
    exit 0
fi

mkdir -p "$STATE_DIR" "$HOME/.local/bin"
level="$(cat "$STATE" 2>/dev/null || echo 0)"
case "$level" in (*[!0-9]*|'') level=0 ;; esac

if [ "$level" -ge "$LATEST_STEP" ]; then
    say "already up to date (level $level)"
    exit 0
fi

# Run all pending root parts in one sudo call, before marking anything done.
need_root=0
for n in $(seq $((level + 1)) "$LATEST_STEP"); do
    declare -F "root_$n" > /dev/null && need_root=1
done
if [ "$need_root" = 1 ]; then
    if ! sudo -n /bin/bash "$SELF" --root "$level"; then
        say "!! root steps need permission — run once over SSH: bash install.sh"
        say "   (level stays at $level so everything retries afterwards)"
        exit 1
    fi
fi

for n in $(seq $((level + 1)) "$LATEST_STEP"); do
    if declare -F "user_$n" > /dev/null; then
        say "step $n"
        "user_$n"
    fi
    echo "$n" > "$STATE"
done
say "updated to level $LATEST_STEP"
