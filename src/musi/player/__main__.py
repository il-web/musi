"""musi-player entry point."""

import logging


def main() -> None:
    # The crash guard goes first, before the rest of the player is even
    # imported: an update that breaks an import must still leave a crash
    # report behind, and still count toward a rollback.
    from musi.player import crashguard, updater
    version = updater.current_version()
    crashguard.install(version)

    target = crashguard.must_auto_rollback(version)
    if target:
        # This version has never drawn a single frame — there is no screen to
        # ask on. Roll back unasked; success restarts the service under us.
        logging.warning("crash loop before first frame on %s — rolling back to %s",
                        version, target)
        ok, msg = updater.rollback(target)
        if ok:
            return
        logging.warning("automatic rollback failed: %s", msg)

    from musi.library.config import art_dir, db_path, music_root
    from musi.library.db import open_db, run_migrations
    from musi.player.app import App
    from musi.player.mpd_client import MusiMPDClient
    from musi.player.screens.loading import LoadingScreen

    db = open_db(db_path())
    run_migrations(db)

    mpd = MusiMPDClient(music_root=music_root())
    mpd.connect()

    app = App(mpd=mpd, db=db, art_dir=art_dir())
    app.first_frame_hook = crashguard.mark_ui_ready

    first = LoadingScreen(app)
    offer = crashguard.offer(version)
    if offer:
        from musi.player.screens.rollback import RollbackScreen
        first = RollbackScreen(app, offer, then=first)
    app.run(first)


if __name__ == "__main__":
    main()
