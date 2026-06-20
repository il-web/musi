"""musi-player entry point."""

from pathlib import Path

from musi.library.config import art_dir, db_path, music_root
from musi.library.db import open_db, run_migrations
from musi.player.app import App
from musi.player.mpd_client import MusiMPDClient
from musi.player.screens.loading import LoadingScreen


def main() -> None:
    db = open_db(db_path())
    run_migrations(db)

    mpd = MusiMPDClient(music_root=music_root())
    mpd.connect()

    app = App(mpd=mpd, db=db, art_dir=art_dir())
    app.run(LoadingScreen(app))


if __name__ == "__main__":
    main()
