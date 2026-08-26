"""Boot-config edits for the power pack (OTA step 5).

The edits live twice on purpose: once in install.sh for fresh installs, once in
update.sh's root_5 for OTA. They cannot share a helper — root_5 runs from the
root-owned /usr/local/lib/musi/update-root.sh, and sourcing anything out of the
git checkout would let the app's own user hand itself root. So these tests do
two jobs: prove root_5 is idempotent, and prove install.sh still mirrors it.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
UPDATE_SH = REPO / "update.sh"
INSTALL_SH = REPO / "install.sh"

# The exact lines the pack appends. Kept here so a silent edit to either script
# fails a test rather than drifting unnoticed.
DTPARAMS = [
    "dtparam=act_led_trigger=none",
    "dtparam=act_led_activelow=off",
    "dtparam=pwr_led_trigger=none",
    "dtparam=pwr_led_activelow=off",
]
HDMI_OFF = "video=HDMI-A-1:d"

BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="bash not available")


def _run_root_5(boot_dir: Path, times: int = 1) -> None:
    """Extract root_5 from update.sh and run it against a fake /boot/firmware.

    Running the real shipped function - not a copy of it - is the whole point:
    a test against a transcription would pass while the script rots.
    """
    body = _extract_function(UPDATE_SH.read_text(encoding="utf-8"), "root_5")
    calls = "\n".join(["root_5 \"$1\""] * times)
    script = f"set -eu\n{body}\n{calls}\n"
    proc = subprocess.run(
        [BASH, "-c", script, "bash", str(boot_dir).replace("\\", "/")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"root_5 failed: {proc.stderr}"


def _extract_function(source: str, name: str) -> str:
    """Pull `name() { ... }` out of a shell script by brace depth."""
    start = source.index(f"{name}() {{")
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise AssertionError(f"unterminated function {name}")


@pytest.fixture()
def boot(tmp_path: Path) -> Path:
    """A fake /boot/firmware with the lines a real musi device already has."""
    d = tmp_path / "firmware"
    d.mkdir()
    (d / "config.txt").write_text(
        # A real device already carries dtparam lines. The naive idempotency
        # check (grep "^dtparam=") would see these and skip every new one.
        "dtparam=i2s=on\n"
        "dtoverlay=hifiberry-dac\n"
        "dtparam=width=320,height=480,reset-gpio=25,dc-gpio=24,backlight-gpio=12\n"
        "boot_delay=0\n",
        encoding="utf-8",
    )
    (d / "cmdline.txt").write_text(
        "console=serial0,115200 root=PARTUUID=abcd1234-02 rootfstype=ext4 "
        "fsck.repair=yes rootwait fbcon=map:10\n",
        encoding="utf-8",
    )
    return d


@needs_bash
def test_appends_led_and_hdmi_settings(boot: Path) -> None:
    _run_root_5(boot)
    config = (boot / "config.txt").read_text(encoding="utf-8")
    for line in DTPARAMS:
        assert line in config, f"{line} missing from config.txt"
    assert HDMI_OFF in (boot / "cmdline.txt").read_text(encoding="utf-8")


@needs_bash
def test_existing_dtparam_lines_do_not_block_the_new_ones(boot: Path) -> None:
    """The device already has dtparam=i2s=on; the LED params must still land."""
    _run_root_5(boot)
    config = (boot / "config.txt").read_text(encoding="utf-8")
    assert "dtparam=i2s=on" in config, "existing dtparam was clobbered"
    assert "dtparam=act_led_trigger=none" in config


@needs_bash
def test_is_idempotent(boot: Path) -> None:
    """OTA re-runs steps after a failed root phase, so twice must equal once."""
    _run_root_5(boot, times=3)
    config = (boot / "config.txt").read_text(encoding="utf-8").splitlines()
    for line in DTPARAMS:
        assert config.count(line) == 1, f"{line} appended {config.count(line)}x"
    cmdline = (boot / "cmdline.txt").read_text(encoding="utf-8")
    assert cmdline.count(HDMI_OFF) == 1


@needs_bash
def test_cmdline_stays_one_line(boot: Path) -> None:
    """The firmware reads only the first line - a newline here bricks boot."""
    _run_root_5(boot, times=2)
    raw = (boot / "cmdline.txt").read_text(encoding="utf-8")
    assert len(raw.strip().splitlines()) == 1, f"cmdline.txt split: {raw!r}"
    assert "  " not in raw, f"double space in cmdline.txt: {raw!r}"


@needs_bash
def test_missing_cmdline_is_not_fatal(boot: Path, tmp_path: Path) -> None:
    """A non-Pi or odd layout must not abort the whole root phase."""
    (boot / "cmdline.txt").unlink()
    _run_root_5(boot)
    assert "dtparam=act_led_trigger=none" in (boot / "config.txt").read_text(encoding="utf-8")


def test_install_sh_mirrors_the_same_lines() -> None:
    """update.sh's header rule: every root step is mirrored in install.sh."""
    install = INSTALL_SH.read_text(encoding="utf-8")
    for line in DTPARAMS:
        assert line in install, f"install.sh does not mirror {line}"
    assert HDMI_OFF in install, "install.sh does not mirror the HDMI disable"


def test_latest_step_is_five() -> None:
    assert "LATEST_STEP=5" in UPDATE_SH.read_text(encoding="utf-8")
