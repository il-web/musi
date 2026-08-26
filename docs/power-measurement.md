# Measuring musi's power draw

musi moved from a Pi Zero W to a Pi 3 Model B on 2026-08-23. The Pi 3 is a much
hungrier board, and this is a battery device, so power changes now need evidence
rather than folklore. This is the procedure that produces comparable numbers.

## What you need

A USB power meter — the small inline kind with a display, about $5–10. It sits
between the power source and the Pi and shows current draw in milliamps.

**You do not have to measure through the powerbank.** The Pi draws what it draws
regardless of what feeds it, and a wall charger is actually the better test rig:
it holds a steady voltage, while a powerbank sags as it discharges and quietly
changes your numbers between readings. If your meter is USB-A and your powerbank
is USB-C, just use any USB-A source for the test.

## The fixed test conditions

Readings are only comparable if the device is doing the same thing each time.
Use these, every time, and note any deviation next to the number:

| | Setting |
|---|---|
| Screen | On, not dimmed — tap once just before reading |
| Audio | Playing, to the I²S DAC (not Bluetooth) |
| Volume | 50% |
| Wi-Fi | Connected, idle (no upload or update running) |
| Bluetooth | Not connected to anything |
| Settle time | Wait 60s after boot before the first reading |
| Reading | Watch for ~30s and record the typical value, not the peak |

Take an idle reading too — screen off, nothing playing — since that is where the
device spends much of its life.

## Baseline

Record this **before** applying anything. Without a baseline the rest is noise.

| Date | Condition | Current | Notes |
|---|---|---|---|
| | Playing, screen on | | |
| | Idle, screen off | | |

## Step 5 — LEDs and HDMI off

Applied by OTA step 5 (`update.sh root_5`, mirrored in `install.sh`).
**Both settings are boot-time only — they do nothing until you reboot.**

| Date | Condition | Current | Δ vs baseline |
|---|---|---|---|
| | Playing, screen on | | |
| | Idle, screen off | | |

Expected: a modest saving. These are honest, low-risk wins, not a transformation
— the single largest saving available on a Pi 3 would have been powering down the
LAN9514 USB/Ethernet hub, and that was deliberately ruled out because it takes
the Ethernet port and all USB ports with it.

### Reverting

If anything misbehaves, both changes are plain text on the SD card's boot
partition, editable from any PC:

- **LEDs:** delete the four `dtparam=*_led_*` lines from `config.txt`.
- **HDMI:** delete ` video=HDMI-A-1:d` from `cmdline.txt`. Keep it one line.

## The CPU governor experiment

Deliberately **not** shipped. Raspberry Pi OS already defaults to `ondemand`,
which idles the Pi 3 at 600 MHz, so forcing `powersave` may save close to nothing
while making album-art decode slower. It is worth measuring, not assuming.

The setting is runtime-only and resets on reboot, which makes it a safe thing to
try:

```sh
# what is it now?
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor

# try pinning to the low frequency
echo powersave | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# watch the actual clock while you use the UI
vcgencmd measure_clock arm

# back to normal (or just reboot)
echo ondemand | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

| Date | Governor | Current | UI still feels OK? |
|---|---|---|---|
| | ondemand | | baseline |
| | powersave | | |

Make it permanent only if the numbers justify it *and* the UI still feels right.

## Ruled out

Recorded so they don't get re-proposed:

- **Powering down the USB/Ethernet hub** — on the Pi 3 B, Ethernet and the USB
  ports are one chip (LAN9514). Cannot have one without the other.
- **Turning off the Bluetooth radio while using the DAC** — probably the largest
  remaining software-controllable saving, but it stops the speaker
  auto-reconnecting. Rejected on UX grounds 2026-08-26.
- **Underclocking** (`arm_freq`, `over_voltage`) — real savings, real stability
  risk. Rejected 2026-08-26; revisit only if the numbers above disappoint.
