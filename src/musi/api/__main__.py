"""Run the device API in the foreground — entry point for musi-api.service.

    python -m musi.api
"""
from __future__ import annotations

import logging

from musi.api import auth
from musi.api.server import PORT, create_app
from musi.library.config import art_dir, db_path, music_root


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    # Make sure the schema exists so read endpoints work before the first scan.
    from musi.library.db import open_db, run_migrations
    conn = open_db(db_path())
    run_migrations(conn)
    conn.close()

    auth.load_token()   # generate the token file on first boot
    app = create_app(music_root(), db_path(), art_dir())

    import werkzeug.serving
    server = werkzeug.serving.make_server("0.0.0.0", PORT, app, threaded=True)
    logging.getLogger(__name__).info("musi API listening on :%d", PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
