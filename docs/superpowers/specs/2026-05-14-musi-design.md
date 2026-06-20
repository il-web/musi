# musi — Custom iPod-style Music Player

**Design doc — v1**
**Date:** 2026-05-14

## 1. Overview

`musi` is a pocket-sized music player built around a Raspberry Pi Zero 2 W. It plays a local library of 10,000+ tracks (mixed MP3/FLAC/ALAC), outputs to a wired DAC or Bluetooth headphones, has a 3.5" touchscreen display, and is operated primarily by 5 physical buttons (with touch as a shortcut layer).

**v1 is battery-powered** (606090 LiPo, charged over USB-C via a TP4056 module, boosted to 5V by an MT3608). There is no fuel-gauge IC, so battery *telemetry* (charge %, low-battery warnings) remains deferred — see §12.

The goal is a polished, snappy, reliable daily-driver music device — closer in feel to an iPod Classic than a generic Linux SBC project.

### Priorities (in order)

1. **Reliability** — survives sudden power loss without corruption; services restart cleanly on crash; predictable behavior.
2. **Polish** — album-art-maximalist UI with art-driven theming and smooth transitions, despite the limited hardware.
3. **Leanness** — fast boot, cool idle, low resource use — sets us up for battery operation later, but yields to the first two priorities where they conflict.

### Non-goals (v1)

- Music streaming (Spotify, Tidal, etc.)
- Internet radio / podcasts
- Playlists (manual or imported)
- Equalizer / audio DSP beyond replay-gain
- Lyrics / sleep timer / alarm clock / star ratings / play counts UI
- Crossfade between tracks
- Remote control from phone / web UI
- Multiple user profiles
- Music transfer over Wi-Fi

These may be revisited post-v1.

## 2. Hardware

- Raspberry Pi Zero 2 W (quad-core ARM Cortex-A53 @ 1 GHz, 512 MB RAM)
- 3.5" SPI TFT display, 320×480, ST7796 controller, with XPT2046 resistive single-touch
- 5 physical buttons via GPIO: D-pad (up/down/left/right) + center select. (Transport — prev/next/play-pause — and back are touch-only.)
- PCM5102A I2S DAC → 3.5mm headphone jack (wired output)
- Bluetooth (Pi Zero 2 W built-in radio, A2DP sink)
- Hardware power button on a dedicated GPIO with interrupt
- microSD card (256 GB recommended, A2-rated high-endurance)
- **Power: battery.** 606090 LiPo cell → MT3608 boost converter to 5V. Charged via a **USB-C** port on a TP4056 charge-management module. No fuel-gauge IC, so charge-% telemetry is deferred to a later revision.

## 3. v1 Feature Scope

- Browse library by Artist / Album / Song / Genre
- Play artist (all songs by artist, in order)
- Play album (with optional shuffle)
- Shuffle all tracks
- Search (FTS5 fuzzy search across artists, albums, tracks) with on-screen keyboard
- "Recently played" home screen (last 30 tracks)
- Now Playing screen with scrubbing, prev/next, volume
- Audio output switching (wired DAC ↔ paired Bluetooth device)
- USB Mass Storage sync mode (Pi appears as a USB drive on PC)
- OTA updates over Wi-Fi (A/B partition swap with rollback)
- Wi-Fi setup (for system tasks only — NTP, OTA)
- Hybrid sleep: screen blank on idle, cold shutdown on long idle

## 4. System Architecture

The system is partitioned into one foreground UI process, six independent background services (three off-the-shelf, three custom), and a stripped-down Raspberry Pi OS Lite base.

### Process layout

| Process | Role | Custom or stock |
|---|---|---|
| `musi-player` | UI, framebuffer owner, input handler | custom |
| `musi-library` | Library indexer, SQLite, art pipeline | custom |
| `musi-power` | Power button, sleep state machine, UI watchdog | custom |
| `musi-usbsync` | USB Mass Storage mode toggle on cable connect | custom |
| `musi-ota` | OTA update checker and installer | custom |
| `mpd` | Audio playback engine + queue | stock |
| `pipewire` + `wireplumber` | Audio routing and output switching | stock |
| `bluetoothd` (BlueZ) | Bluetooth pairing and A2DP profile | stock |

All services run under systemd with `Restart=on-failure` and crash-loop protection (`StartLimitBurst=5`). `musi-player` uses `Restart=always` because the UI must always come back.

### IPC

- `musi-player` ↔ `mpd`: MPD protocol over local Unix socket (`python-mpd2`).
- `musi-player` ↔ `musi-library`: read-only SQLite handle into `/var/lib/musi/library.db`; small Unix socket for scan-progress/rescan-trigger commands only.
- `musi-player` ↔ `musi-power`, `musi-usbsync`: D-Bus signals and methods.
- `musi-player` ↔ `pipewire`: `wpctl` CLI calls for output switching; PipeWire D-Bus for sink-list updates.

## 5. Component designs

### 5.1 `musi-player` (UI)

- **Stack:** Python 3.11+, pygame 2.x, Pillow, `python-evdev`, `asyncio`, `dbus-next`, `python-mpd2`.
- **Display path:** SDL2 renders to `/dev/fb1`. The SPI display is driven by `fbcp-ili9341` (DMA-based SPI→framebuffer mirror). Target 30 fps.
- **Render loop:** Dirty-rect driven. Full repaint only on screen change. Static elements (Now Playing background) don't redraw every frame.
- **Heavy image work** (blur, palette extraction, resize): always done at scan time in `musi-library`, never at runtime. `musi-player` only blits pre-rendered PNGs from `/var/lib/musi/art/`.
- **Input:** Reads `/dev/input/event-buttons` and `/dev/input/event-touch`, normalizes to a single `InputEvent` queue. Touch is single-touch resistive; tap and drag are supported, no multi-touch gestures.
- **Navigation:** stack-based. Back button pops one level. Modals overlay without pushing.
- **State persistence:** `/var/lib/musi/state.json` written every 5s and on every track change. Atomic write (write to tmp + rename). Restored on boot.
- **Art cache:** in-process LRU capped at 50 MB; evicts to disk.
- **Crash recovery:** systemd `Restart=on-failure`. Splash screen during restart, then resume from `state.json`. Max data loss: ~5 seconds of play position.

### 5.2 `musi-library` (indexer + DB)

- **Stack:** Python 3, `mutagen`, `Pillow`, `sqlite3`, `pyinotify` or `watchdog`.
- **Database:** `/var/lib/musi/library.db`, SQLite with WAL mode.
- **Schema (sketch):**
  ```
  tracks(id, path, title, artist_id, album_id, track_no, disc_no,
         duration_ms, year, genre, bitrate, format, mtime, added_at)
  artists(id, name, sort_name)
  albums(id, title, artist_id, year, art_path, backdrop_path,
         color_primary, color_accent, color_text)
  tracks_fts (FTS5 virtual table: title, artist_name, album_title)
  play_history(track_id, played_at)
  settings(key, value)
  ```
- **Art pipeline (per album, once at scan time):**
  1. Source: embedded tag → `cover.jpg` → `folder.jpg` → fallback gradient
  2. Resize source to 160×160 thumbnail
  3. Gaussian-blurred + darkened 320×480 backdrop
  4. k-means → primary / accent / text-on-bg colors stored in DB
  5. No-art tracks get a deterministic gradient from hash("artist+album")
- **Scan strategy:**
  - First boot: full scan (~2 minutes for 10k tracks), progress shown on screen.
  - Subsequent boots: incremental by `mtime` since last scan.
  - After USB-sync disconnect: full scan (can't trust PC's mtime handling).
  - Throttled (nice 15, 10ms sleep every 50 tracks).
- **Filesystem watch:** inotify on `/music` for live edits (rare).
- **DB corruption recovery:** on open failure, rename `library.db` → `library.db.bad` and trigger full rescan. Music files are the source of truth.

### 5.3 Playback path — `mpd` + `pipewire`

- **MPD configuration:**
  - Music root pointed at `/music` (mounted read-only at runtime)
  - MPD's own DB enabled but used only internally for URI lookup; UI never queries it for browse
  - Software mixer (PCM5102A has no hardware volume; supports replay-gain)
  - Single output: a PipeWire ALSA bridge sink
  - Persistent state (queue, position) saved to `/var/lib/musi/mpd-state`
- **MPD client:** `python-mpd2`, long-lived connection, uses `idle` events for push notifications (no polling).
- **PipeWire + WirePlumber:**
  - Default sink: `alsa_output.platform-soc_sound.stereo-fallback` (PCM5102A on hw:0)
  - BT A2DP sinks appear dynamically on pair
  - WirePlumber Lua policy: remembers user's last chosen output across reboots
  - Switching outputs = one `wpctl set-default <id>` call; in-flight stream re-routed by PipeWire transparently to MPD
- **Output switching UX:** Settings → Audio Output. Now Playing shows a small icon for current output.
- **Volume:** software volume in MPD, capped at 0 dB (no destructive +N dB digital gain).
- **Gapless, replay-gain, all formats:** handled natively by MPD.

### 5.4 `musi-power` (power button + sleep + watchdog)

- **Stack:** Python, `lgpio` for power button, `dbus-next` for IPC.
- **D-Bus interface:**
  - Signal: `PowerStateChanged(state)` — `{active, screen_blank, shutting_down}`
  - Method: `RequestSleep()`, `RequestWake()`, `RequestShutdown()`
- **Power button semantics:**
  - Short press (<1s): toggle screen blank / wake
  - Medium press (1–3s): clean shutdown
  - Long press (>5s): emergency hard power-off (handled by hardware-level power gate, not software)
- **UI watchdog:** if `musi-player` heartbeat is silent for 30s, kill + restart the UI process.
- **Future (deferred):** battery telemetry, low-battery toast at <10%, clean shutdown at <5%. The D-Bus surface is designed to accept `BatteryChanged` / `BatteryCritical` signals later without breaking existing subscribers.

### 5.5 `musi-usbsync` (USB Mass Storage mode)

- **Trigger:** udev rule on USB VBUS high (cable plugged into a powered host).
- **Sequence on connect:**
  1. D-Bus → `musi-player`: enter sync mode (UI shows "Sync Mode" screen)
  2. `mpd` stop
  3. unmount `/music`
  4. `modprobe g_mass_storage file=/dev/mmcblk0p5 ro=0`
  5. wait for VBUS low (unplug)
  6. `modprobe -r g_mass_storage`
  7. remount `/music` read-only
  8. trigger `musi-library` rescan
  9. D-Bus → `musi-player`: exit sync mode (return to previous screen)
- **Power-only / no-host case:** if VBUS is high but no USB host enumeration is detected within 5s, the UI prompts "USB connected — switch to Sync Mode?" rather than auto-entering. (Catches the case where a PC is booting, or the cable is plugged into a charger-only port.)
- **Edge case — PC dirty-unmounts mid-write:** we wait for VBUS-low before remounting and rescanning. exFAT has no journal; this is an acceptable user-managed risk. UI shows a "Safe to disconnect" indicator when the host has flushed.

### 5.6 `musi-ota` (OTA updates)

- **Model:** A/B root partitions. Active slot selected by bootloader flag in `/boot/cmdline.txt`.
- **Flow:**
  1. Check endpoint over Wi-Fi at boot and every 24h
  2. Download signed `.img.gz` to `/var/lib/musi/staging/`
  3. **Verify GPG signature against baked-in public key. No signature → no install. No exceptions.**
  4. UI prompt: "Update Available — Install Now?"
  5. On user confirm: write to inactive slot, flip boot flag, reboot
  6. On next boot, `musi-ota` writes a `boot-ok` flag in `/boot/`. If not present within 60s, bootloader rolls back automatically.
- **Out of scope:**
  - Kernel updates (kernel ships with the device; updating requires SD reflash)
  - Delta updates (full ~2 GB images only)
  - Release channels
  - `/var/lib/musi` and `/music` are never touched by OTA

## 6. System layer

### 6.1 Base image

- Raspberry Pi OS Lite (Bookworm, 64-bit)
- Stripped: avahi-daemon, dphys-swapfile, fake-hwclock, rsyslog (journald only), apt-listchanges, manpages, locales beyond C/UTF-8/en_US

### 6.2 Boot sequence (target: ≤15s to playable)

| Time | Stage |
|---|---|
| 0.0s | Power-on, bootloader picks active root slot |
| 1.5s | Kernel started, framebuffer initialized |
| 2.0s | Splash image to framebuffer via `musi-splash` ramdisk binary |
| 2.5s | rootfs mounted ro + overlayfs, systemd starts |
| 5.0s | `fbcp-ili9341` started, display mirrored to SPI |
| 6.0s | `mpd`, `pipewire`, `bluez`, `musi-library`, `musi-power` started in parallel |
| 8.0s | `musi-player` starts, restores `state.json`, renders last screen |
| 10.0s | `musi-library` ready (incremental scan, usually instant) |
| 12.0s | Auto-resume of last track (or "Resume?" prompt) |

Optimizations held in reserve: defer bluetooth start until Settings opened (saves ~2s); precompile Python `.pyc` at image-build time (saves ~1s).

### 6.3 Partition layout

| # | Type | Size | Mount | Purpose |
|---|---|---|---|---|
| p1 | FAT32 | 256 MB | `/boot` | Kernel, firmware, bootloader, `cmdline.txt`, boot-flag |
| p2 | ext4 | 2 GB | `/` (slot A) | Active or dormant OS, ro+overlay |
| p3 | ext4 | 2 GB | `/` (slot B) | Other slot |
| p4 | ext4 | 1 GB | `/var/lib/musi` | DB, art cache, state, OTA staging |
| p5 | exFAT | rest | `/music` | User library, USB-exposable |

exFAT for `/music`: native R/W on Windows and macOS, no driver install; supports >32 GB. Pi OS Bookworm supports it via `exfatprogs`.

### 6.4 Systemd service graph

```
basic.target
  └── musi-splash.service (oneshot, ramdisk)
      └── musi-mount.service (mounts /var/lib/musi rw, /music ro)
          ├── mpd.service
          ├── pipewire.service ── wireplumber.service
          ├── bluetooth.service (late-start)
          ├── musi-library.service
          ├── musi-power.service
          ├── musi-usbsync.service
          └── musi-player.service (Restart=always, depends on all above)
```

### 6.5 Read-only root realities

- Persistent settings live in `/var/lib/musi/settings.json` (managed by `musi-player`), not in `/etc`
- OS-side `/etc` writes vanish on reboot (RAM overlay)
- OTA mounts inactive slot rw temporarily
- journald in volatile mode (RAM only) — no log SD wear

### 6.6 Wi-Fi

Credentials stored in `/var/lib/musi/wifi.json`. A boot script writes them into `/etc/wpa_supplicant/wpa_supplicant.conf` in the RAM overlay. UI: Settings → Wi-Fi → scan → on-screen keyboard for password.

## 7. Power state machine

- `active` → (30s no input) → `screen_blank` (backlight off, audio continues)
- `screen_blank` + any input → `active`
- `screen_blank` + (paused 10 min OR idle 30 min) → `shutting_down` (less critical without battery, but kept for SD wear reduction and clean state on long idle)
- power button medium-press → `shutting_down`

Shutdown is always clean: save `state.json`, MPD save queue, sync filesystem, then poweroff. Battery-driven transitions (`<10%` toast, `<5%` auto-shutdown) are deferred along with battery hardware.

## 8. UI navigation

### Root screens (Home)

Home shows: Now Playing card (if a track is loaded), Recently Played (last 30), and a "Browse Library" entry. From Home, D-pad up/down moves focus across: Now Playing → Recently Played → Browse → Search → Settings.

### Browse path

Browse → {Artists | Albums | Songs | Genres | Shuffle All} → Artist List → Artist View (albums + Play All) → Album View (tracks + Play Album + Shuffle Album) → Now Playing.

### Search

Dedicated screen with on-screen QWERTY keyboard. FTS5 across artists/albums/tracks. Results grouped by type. Tap or D-pad select → drill into Artist/Album, or play track.

### Now Playing

Big album art + blurred backdrop. Scrub bar. Track metadata. Output icon. Volume bar appears on D-pad up/down. Long-press select (or swipe up) → Queue view. Now Playing Options: shuffle toggle, repeat, output switch, "go to album/artist."

### Settings

Audio Output (sink list), Bluetooth (scan/pair/forget), Wi-Fi (scan/keyboard), Update (check/install), About/Storage.

### Modal overlays

USB Sync Mode (auto on cable connect), Update Available, Loading/Scanning (full-screen during scan), Splash (boot). (Low Battery toast deferred along with battery hardware — see §12.)

### Button semantics

- `prev` / `next` — always skip-track when audio is loaded, regardless of current screen
- `play/pause` — always toggle playback, regardless of current screen
- `back` — pop nav stack; from Home, dismisses modals only
- `select` — context-dependent
- `D-pad ↑↓` — list nav on browse screens; volume on Now Playing
- `D-pad ←→` — paging where applicable; prev/next on Now Playing

### Letter-jump

Hold ↑ or ↓ for 500ms in any long list → letter-jump mode with big visible letter overlay. Release to commit.

### Touch shortcuts

Tap list rows, tap transport icons, drag scrub bar, drag volume slider. Falls back to buttons everywhere.

## 9. Resource budgets

### Storage (fixed system footprint: ~5.3 GB)

- `/boot`: ~150 MB used
- root A: ~1.8 GB used
- root B: ~1.8 GB used (mirror)
- `/var/lib/musi`: ~150–250 MB used (DB + art cache ~65 MB for 1k albums)
- `/music`: user library, ~35–80 GB for 10k tracks depending on format mix

Recommended SD: 256 GB A2-rated high-endurance (SanDisk High Endurance, Samsung PRO Endurance).

### RAM (~440 MB used of 512 MB)

| Component | RAM |
|---|---|
| Kernel + Pi OS Lite baseline | ~120 MB |
| systemd + journald | ~30 MB |
| MPD | ~20 MB |
| PipeWire + WirePlumber + BlueZ | ~40 MB |
| `musi-library` (idle) | ~30 MB |
| `musi-player` (UI + 50 MB art LRU) | ~120 MB |
| Other `musi-*` services | ~30 MB |
| Overlayfs | ~50 MB |
| **Total** | **~440 MB** |
| **Headroom** | **~70 MB** |

Disciplines to maintain the budget:
- `musi-player` art cache hard-capped at 50 MB LRU
- `musi-library` scan throttled to avoid spikes
- journald volatile mode, no long log retention

## 10. Reliability strategy

| Failure | Mitigation |
|---|---|
| Sudden power loss mid-write | ro root + RAM overlay; atomic writes; state saved every 5s. Worst case: <5s play position lost. |
| SD card corruption | ro root; `/var/lib/musi` is the only rw partition with journal; `/music` is rw only during USB sync. |
| Service crash | systemd `Restart=on-failure`, crash-loop protection. UI splash on restart, state restored. |
| `musi-player` deadlock | `musi-power` watchdog: no heartbeat for 30s → kill + restart UI. |
| fbcp wedge | Separate process, restartable without UI restart. |
| BT disconnect mid-song | PipeWire fallback rule auto-routes to wired DAC. Toast: "BT disconnected." |
| Bad OTA → bootloop | A/B partitions, 60s `boot-ok` flag, auto-rollback. |
| Library DB corruption | SQLite WAL + atomic txns; on open failure, rename + full rescan. |
| Album art corruption | Per-album lazy regen from source; gradient fallback. |
| Wall power yanked / cord pulled | ro root + RAM overlay + atomic writes survive hard cutoff. Worst case: <5s of play position lost. |
| Wi-Fi flaky/unavailable | Strictly non-essential. UI never blocks on network. |
| USB cable plugged in mid-play | `musi-usbsync` pauses, saves position, hands over `/music`. Rescan + resume on disconnect. |
| PC dirty-unmounts USB | Wait for VBUS-low before remounting. exFAT, no journal — acceptable user-managed risk. |
| Stuck button | evdev debounce + ignore button held >30s while idle. |

## 11. Testing strategy

- **Unit tests** for `musi-library`: DB schema, tag parsing, art pipeline. Pure Python, dev machine, no hardware.
- **Integration tests** for `musi-player` UI flows: against mocked MPD + mocked library, via SDL2 dummy video driver on dev machine.
- **On-device smoke test:** automated boot + play-a-track + change-output + scrub + shutdown, run on a real Pi after each image build.
- **Reliability soak:** 24h playback session, monitor memory leaks, SD writes, crash counts.
- **Power-loss tests:** pull the plug at boot, during play, during scan, during OTA write. Verify no corruption.

## 12. Out of scope / open questions

- **Industrial / enclosure design** — out of scope for this software spec.
- **Battery present; charge-% telemetry deferred.** Power is a 606090 LiPo → MT3608 boost to 5V, charged over USB-C via a TP4056 module. Because the TP4056 has no fuel-gauge IC, there is no charge-% reading, so battery *telemetry* features (low-battery toast at <10%, auto-shutdown at <5%) remain deferred. The `musi-power` D-Bus surface is designed to accept battery signals (`BatteryChanged`, `BatteryCritical`) if a fuel gauge (e.g., MAX17048) is added later, without breaking existing subscribers.
- **Touch calibration UI** — XPT2046 needs calibration; v1 ships with a "Calibrate Touch" entry in Settings, run on first boot if no calibration file present.
- **Multiple language support** — UI strings hardcoded in English for v1.
- **Bluetooth multipoint / source mode** — out of scope; sink only.
- **Future:** playlists, equalizer, lyrics, streaming, remote control, podcasts — explicitly deferred.
