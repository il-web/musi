"""Status-bar output icon — read from the audio router's ~/.asoundrc."""
from musi.player import audio_detect


def _rc(tmp_path, slave):
    p = tmp_path / ".asoundrc"
    p.write_text('pcm.musiout {\n    type plug\n    slave.pcm "%s"\n}\n' % slave)
    return p


def test_bluetooth_route(tmp_path):
    rc = _rc(tmp_path, "bluealsa:DEV=AA:BB:CC:DD:EE:FF,PROFILE=a2dp")
    assert audio_detect._route_from_asoundrc(rc) == "bluetooth"


def test_dac_route(tmp_path):
    assert audio_detect._route_from_asoundrc(_rc(tmp_path, "hw:sndrpihifiberry,0")) == "wired"


def test_no_file_means_fall_back(tmp_path):
    assert audio_detect._route_from_asoundrc(tmp_path / "missing") is None
