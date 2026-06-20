#!/bin/bash
# musi Pi launcher — configures SDL for the ST7796 SPI panel (KMS/DRM), then starts the player.
# Just run:  bash run.sh   (or  ./run.sh  after chmod +x)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -n "$DISPLAY" ]; then
    # Desktop / X11 (dev testing)
    export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-x11}"
else
    # On the device: render to the SPI panel via KMS/DRM
    export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-kmsdrm}"
    export SDL_RENDER_DRIVER="${SDL_RENDER_DRIVER:-software}"

    # The SPI panel is a separate DRM card from the (unused) HDMI one, and the
    # card numbers can change between boots — so detect the panel's index rather
    # than hard-coding it.  Falls back to letting SDL pick if not found.
    if [ -z "${SDL_KMSDRM_DEVICE_INDEX:-}" ]; then
        for d in /sys/class/drm/card[0-9]; do
            if grep -q panel-mipi-dbi "$d/device/uevent" 2>/dev/null; then
                export SDL_KMSDRM_DEVICE_INDEX="${d##*card}"
                break
            fi
        done
    fi
fi

# Touchscreen — disable relative mouse mode so absolute touch coords work
export SDL_MOUSE_RELATIVE=0

# Music library location (override by setting MUSI_MUSIC_ROOT before launching)
if [ -z "${MUSI_MUSIC_ROOT:-}" ]; then
    if [ -d "$HOME/music" ]; then
        export MUSI_MUSIC_ROOT="$HOME/music"
    else
        export MUSI_MUSIC_ROOT="$HOME/Music"
    fi
fi

exec "$SCRIPT_DIR/.venv/bin/python" -m musi.player "$@"
