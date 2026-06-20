"""WiFi Transfer HTTP server — lightweight Flask app for uploading music."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from flask import Flask, jsonify, request

PORT = 8080
AUDIO_EXT = {".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wav", ".opus", ".wma", ".ape"}

# Silence Flask's request logger so it doesn't spam the console
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)


# ── HTML served at / ──────────────────────────────────────────────────────────

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>musi — WiFi Transfer</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0a0a0f;color:#fff;font-family:-apple-system,system-ui,sans-serif;
     min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:40px 20px}
h1{color:#ff5c8a;font-size:2.2em;letter-spacing:-1px;margin-bottom:4px}
.sub{color:#78788a;margin-bottom:36px;font-size:.95em}
.drop{border:2px dashed #ff5c8a;border-radius:16px;padding:52px 32px;text-align:center;
      cursor:pointer;transition:background .15s;width:100%;max-width:480px}
.drop.over{background:rgba(255,92,138,.1)}
.drop p{color:#78788a;margin-top:10px;font-size:.9em;line-height:1.6}
.drop svg{opacity:.85}
#fi{display:none}
.bar-wrap{width:100%;max-width:480px;background:#16162a;border-radius:6px;
          height:8px;margin-top:20px;display:none;overflow:hidden}
.bar{height:100%;background:#ff5c8a;border-radius:6px;transition:width .25s;width:0}
.status{margin-top:14px;color:#78788a;font-size:.9em;min-height:1.2em;text-align:center}
.stats{margin-top:36px;color:#78788a;font-size:.85em}
.stats span{color:#fff;font-weight:600}
</style>
</head>
<body>
<h1>musi</h1>
<p class="sub">WiFi Transfer</p>

<div class="drop" id="drop" onclick="document.getElementById('fi').click()">
  <svg width="44" height="44" viewBox="0 0 24 24" fill="none"
       stroke="#ff5c8a" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
    <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
    <polyline points="17 8 12 3 7 8"/>
    <line x1="12" y1="3" x2="12" y2="15"/>
  </svg>
  <p>Drop music files here<br>or tap to browse</p>
  <p style="font-size:.8em;margin-top:6px;color:#50505f">
    MP3 · FLAC · OGG · M4A · WAV · OPUS · WMA</p>
  <input type="file" id="fi" multiple
         accept=".mp3,.flac,.ogg,.m4a,.aac,.wav,.opus,.wma,.ape">
</div>

<div class="bar-wrap" id="bw"><div class="bar" id="bar"></div></div>
<div class="status" id="st"></div>
<div class="stats">Library: <span id="tc">…</span> tracks</div>

<script>
const drop=document.getElementById('drop'),
      fi=document.getElementById('fi'),
      bw=document.getElementById('bw'),
      bar=document.getElementById('bar'),
      st=document.getElementById('st');

drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('over')});
drop.addEventListener('dragleave',()=>drop.classList.remove('over'));
drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('over');upload(e.dataTransfer.files)});
fi.addEventListener('change',()=>upload(fi.files));

async function upload(files){
  if(!files.length)return;
  bw.style.display='block';bar.style.width='0';
  let ok=0,skip=0;
  for(let i=0;i<files.length;i++){
    const f=files[i];
    st.textContent='Uploading '+f.name+' ('+(i+1)+'/'+files.length+')…';
    const fd=new FormData();fd.append('file',f);
    const r=await fetch('/upload',{method:'POST',body:fd});
    const d=await r.json();
    if(d.status==='ok')ok++;else skip++;
    bar.style.width=((i+1)/files.length*100)+'%';
  }
  const msg=[];
  if(ok)msg.push(ok+' file'+(ok!==1?'s':'')+' added');
  if(skip)msg.push(skip+' already existed');
  st.innerHTML='<span style="color:#4dc87a">✓</span> '+msg.join(', ');
  fetchStats();
}

async function fetchStats(){
  try{const r=await fetch('/stats');const d=await r.json();
  document.getElementById('tc').textContent=d.tracks;}catch(e){}
}
fetchStats();setInterval(fetchStats,5000);
</script>
</body>
</html>
"""


# ── server class ──────────────────────────────────────────────────────────────

class WifiTransferServer:
    """Wraps the Flask app + werkzeug server for clean start/stop."""

    def __init__(self, music_root: Path, db_path: Path, art_dir: Path) -> None:
        self._music_root  = music_root
        self._db_path     = db_path
        self._art_dir     = art_dir
        self._server      = None
        self._thread: threading.Thread | None    = None
        self._rescan_timer: threading.Timer | None = None  # debounce timer
        self._uploaded    = 0   # files added this session

    @property
    def uploaded(self) -> int:
        return self._uploaded

    def start(self) -> None:
        import werkzeug.serving
        flask_app = self._make_app()
        self._server = werkzeug.serving.make_server("0.0.0.0", PORT, flask_app)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._rescan_timer:
            self._rescan_timer.cancel()
            self._rescan_timer = None
        if self._server:
            self._server.shutdown()
            self._server = None

    def _schedule_rescan(self) -> None:
        """Cancel any pending rescan and schedule one 3 s from now."""
        if self._rescan_timer:
            self._rescan_timer.cancel()
        self._rescan_timer = threading.Timer(
            3.0, _rescan,
            args=(self._music_root, self._art_dir, self._db_path),
        )
        self._rescan_timer.daemon = True
        self._rescan_timer.start()

    def _make_app(self) -> Flask:
        music_root = self._music_root
        db_path    = self._db_path
        art_dir    = self._art_dir
        server_ref = self          # capture for closure

        flask_app = Flask(__name__)
        flask_app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024  # 256 MB

        @flask_app.route("/")
        def index():
            return _HTML

        @flask_app.route("/upload", methods=["POST"])
        def upload():
            f = request.files.get("file")
            if not f:
                return jsonify(status="error", reason="no file")
            suffix = Path(f.filename).suffix.lower()
            if suffix not in AUDIO_EXT:
                return jsonify(status="skipped", reason="not audio")
            dest = music_root / Path(f.filename).name
            if dest.exists() and dest.stat().st_size > 0:
                return jsonify(status="skipped", reason="exists")
            dest.parent.mkdir(parents=True, exist_ok=True)
            f.save(dest)
            server_ref._uploaded += 1
            # Debounced rescan — cancel any pending timer and restart 3 s window
            server_ref._schedule_rescan()
            return jsonify(status="ok")

        @flask_app.route("/stats")
        def stats():
            try:
                from musi.library.db import open_db
                conn = open_db(db_path)
                row  = conn.execute("SELECT COUNT(*) AS n FROM tracks").fetchone()
                conn.close()
                return jsonify(tracks=row["n"] if row else 0)
            except Exception:
                return jsonify(tracks=0)

        return flask_app


def _rescan(music_root: Path, art_dir: Path, db_path: Path) -> None:
    try:
        from musi.library.db import open_db
        from musi.library.scanner import scan
        conn = open_db(db_path)
        scan(music_root=music_root, art_dir=art_dir, conn=conn)
        conn.close()
    except Exception:
        pass
