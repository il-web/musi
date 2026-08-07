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
    log = logging.getLogger(__name__)

    # waitress is a real WSGI server; werkzeug's is a development server that
    # its own docs tell you not to expose. Fall back only so a dev checkout
    # without waitress still runs.
    try:
        from waitress import serve
    except ImportError:
        log.warning("waitress not installed — falling back to the werkzeug "
                    "development server (install waitress on the device)")
        import werkzeug.serving
        server = werkzeug.serving.make_server("0.0.0.0", PORT, app, threaded=True)
        log.info("musi API listening on :%d", PORT)
        server.serve_forever()
        return

    log.info("musi API listening on :%d", PORT)
    serve(app, host="0.0.0.0", port=PORT, threads=4, ident="musi")


if __name__ == "__main__":
    main()
