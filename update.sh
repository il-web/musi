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
#   4. if you added a root_N: the device needs ONE manual "bash install.sh"
#      over SSH before OTA can apply it — see below for why
#
# WHY ROOT STEPS NEED A MANUAL INSTALL:
# The root half does NOT run from this file. It runs from a root-owned copy at
# /usr/local/lib/musi/update-root.sh, and sudoers grants exactly that path.
# This file lives in the git checkout, which the app's own user can write — if
# sudoers pointed here, anyone with code execution as that user could append a
# line and become root. So OTA can freely update the user half, and changing
# what runs as root requires install.sh, which needs a real sudo password.
set -u

SELF="$(readlink -f "$0")"
REPO="$(cd "$(dirname "$SELF")" && pwd)"
STATE_DIR="$HOME/.local/share/musi"
STATE="$STATE_DIR/update-level"

# Root-owned copy of this script — the only thing sudoers will run as root.
ROOT_SCRIPT="/usr/local/lib/musi/update-root.sh"

LATEST_STEP=3

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

# ── step 3: RETIRED (was: cloudflared binary for the remote tunnel) ───────────
# The Cloudflare Tunnel was dropped before it ever went live. The step is gone
# but LATEST_STEP stays at 3: devices that already recorded level 3 must not be
# handed a *different* step 3 later. Number the next pack 4.

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
    # The root-owned copy is what actually runs. If it is missing or predates
    # the step we need, it simply doesn't contain that root_N function — it
    # would exit 0 having done nothing, and we'd record the step as applied.
    # Check its level explicitly rather than let it fail silently.
    root_level=0
    if [ -r "$ROOT_SCRIPT" ]; then
        root_level="$(sed -n 's/^LATEST_STEP=\([0-9]*\).*/\1/p' "$ROOT_SCRIPT" | head -1)"
        case "$root_level" in (*[!0-9]*|'') root_level=0 ;; esac
    fi
    if [ "$root_level" -lt "$LATEST_STEP" ]; then
        say "!! root steps changed — run once over SSH:  bash install.sh"
        say "   (installed root helper is at level $root_level, need $LATEST_STEP)"
        say "   level stays at $level so everything retries afterwards"
        exit 1
    fi
    if ! sudo -n /bin/bash "$ROOT_SCRIPT" --root "$level"; then
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
