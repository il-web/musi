# musi dev launcher — loads dev.env and starts the player
$env:MUSI_MUSIC_ROOT = "D:\media disk\music"
# Dev machine only: don't demand a signed upstream commit here. The Pi must
# never have this set — it disables the OTA signature check (docs/ota-signing.md).
$env:MUSI_ALLOW_UNSIGNED = "1"
.\.venv\Scripts\python.exe -m musi.player
