"""musi device API — always-on Flask app (port 8080).

The device is its own server: http://musi.local:8080 serves the management page
at ``/`` and the JSON API at ``/api/v1/*``. Runs permanently as the ``musi-api``
systemd user service; Settings → API on the device shows the URL and token.

Auth: **every route except ``/`` needs ``Authorization: Bearer <token>``**
(token file: see musi.api.auth). ``/`` is public only because it is the page
that asks for the token — it holds no data of its own. Uploads and stats used
to be tokenless for LAN convenience; they aren't any more, because "on the LAN"
includes every guest phone and IoT gadget on the same WiFi.

The API is LAN-only: nothing exposes it to the internet, so the token is the
whole access boundary.

One exception to the token rule: ``/local/*`` is for processes on the device
itself (MPD fetching a music-server stream) and answers loopback only — any
other address gets a 403, token or not.
"""
from __future__ import annotations

import hmac
import logging
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

from flask import Flask, jsonify, redirect, request, send_file

from musi.api import auth
from musi.library import remote

PORT = 8080
AUDIO_EXT = {".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wav", ".opus", ".wma", ".ape"}

# Origins allowed to call /api/v1 from a *cross-origin* browser page
# (comma-separated env override, plus the api-origins file). Empty by default:
# the management page is served from the device itself, so it is same-origin and
# needs no CORS at all. Only add an origin here if an external site must call in.
DEFAULT_CORS_ORIGINS = ""

# The only route that does not require a token. It is the page that prompts for
# one; it embeds no library data.
PUBLIC_PATHS = frozenset({"/"})

# Device-internal routes: no token, but loopback callers only (see module doc).
LOCAL_PREFIX = "/local/"
LOOPBACK = frozenset({"127.0.0.1", "::1"})

# Login throttle. The token is 8 characters (32**8 ≈ 1.1e12) — short enough to
# type off the device screen, which is only safe because guessing is throttled.
# After FAIL_FREE wrong tokens from one address, each further attempt is locked
# out for a doubling delay. Don't remove this without lengthening the token.
FAIL_FREE   = 5           # wrong attempts allowed before throttling kicks in
LOCK_BASE_S = 30.0        # first lockout; doubles per failure after that
LOCK_MAX_S  = 3600.0      # ceiling on a single lockout
FAIL_TTL_S  = 86400.0     # forget an idle address after a day

_STARTED = time.monotonic()

# Silence Flask's request logger so it doesn't spam the journal
logging.getLogger("werkzeug").setLevel(logging.ERROR)

log = logging.getLogger(__name__)


# ── HTML served at / ──────────────────────────────────────────────────────────

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>musi</title>
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
.gate{width:100%;max-width:480px;text-align:center}
.gate p{color:#78788a;font-size:.9em;line-height:1.6;margin-bottom:18px}
.gate input{width:100%;padding:13px 14px;border-radius:10px;border:1px solid #2a2a3f;
     background:#16162a;color:#fff;font-size:1em;font-family:inherit}
.gate input:focus{outline:none;border-color:#ff5c8a}
.gate button{margin-top:12px;width:100%;padding:13px;border:0;border-radius:10px;
     background:#ff5c8a;color:#fff;font-size:1em;font-weight:600;cursor:pointer;
     font-family:inherit}
.gate .err{color:#ff5c8a;min-height:1.2em;margin-top:10px;font-size:.85em}
.hide{display:none!important}   /* beats .stack/.btns, declared later */
.signout{margin-top:28px;background:none;border:0;color:#50505f;font-size:.8em;
     cursor:pointer;text-decoration:underline;font-family:inherit}
.tabs{display:flex;gap:6px;background:#16162a;border-radius:12px;padding:4px;
      width:100%;max-width:480px;margin-bottom:26px}
.tabs button{flex:1;padding:10px;border:0;border-radius:9px;background:none;color:#78788a;
      font-size:.95em;font-weight:600;cursor:pointer;font-family:inherit}
.tabs button.on{background:#ff5c8a;color:#fff}
.panel{width:100%;max-width:480px}
.sec{background:#16162a;border-radius:14px;padding:6px 16px;margin-bottom:18px}
.sec h2{font-size:.75em;text-transform:uppercase;letter-spacing:.08em;color:#78788a;
        margin:12px 0 4px}
.row{display:flex;align-items:center;justify-content:space-between;gap:12px;
     padding:12px 0;border-top:1px solid #22223a}
.row:first-of-type{border-top:0}
.row .lbl{font-size:.95em}
.row .hint{display:block;color:#78788a;font-size:.78em;margin-top:3px;line-height:1.4}
.sw{position:relative;width:46px;height:26px;flex:none}
.sw input{opacity:0;width:0;height:0}
.sw span{position:absolute;inset:0;background:#3c3c4e;border-radius:13px;transition:.2s;cursor:pointer}
.sw span:before{content:"";position:absolute;width:20px;height:20px;left:3px;top:3px;
     background:#fff;border-radius:50%;transition:.2s}
.sw input:checked+span{background:#ff5c8a}
.sw input:checked+span:before{transform:translateX(20px)}
.panel select,.panel input[type=text],.panel input[type=password],.panel input[type=url]{
     padding:9px 10px;border-radius:9px;border:1px solid #2a2a3f;background:#0f0f1c;
     color:#fff;font-size:.9em;font-family:inherit}
.panel input[type=text],.panel input[type=password],.panel input[type=url]{width:100%}
.stack{display:flex;flex-direction:column;gap:8px;padding:12px 0;border-top:1px solid #22223a}
.btns{display:flex;gap:8px}
.btn{padding:10px 14px;border:0;border-radius:9px;background:#ff5c8a;color:#fff;
     font-weight:600;cursor:pointer;font-family:inherit;font-size:.9em}
.btn.ghost{background:#2a2a3f}
.btn:disabled{opacity:.5;cursor:default}
.state{color:#78788a;font-size:.85em;padding:10px 0 2px}
.state b{color:#fff}
.err2{color:#ff5c8a;font-size:.85em;min-height:1em}
.toast{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);background:#16162a;
       border:1px solid #2a2a3f;color:#fff;padding:9px 16px;border-radius:20px;font-size:.85em;
       opacity:0;transition:opacity .2s;pointer-events:none}
.toast.show{opacity:1}
</style>
</head>
<body>
<h1>musi</h1>
<p class="sub">Library</p>

<div class="gate" id="gate">
  <p>Enter the device token to continue.<br>
     It's on the device under <b>Settings → API</b>.</p>
  <input type="text" id="tok" placeholder="XXXX-XXXX" autocomplete="off"
         autocapitalize="characters" spellcheck="false" maxlength="16">
  <button onclick="saveToken()">Unlock</button>
  <div class="err" id="gerr"></div>
</div>

<div class="tabs hide" id="tabs">
  <button id="tab-up" class="on" onclick="tab('up')">Upload</button>
  <button id="tab-set" onclick="tab('set')">Settings</button>
</div>

<div class="panel hide" id="settings">
  <div class="sec">
    <h2>Playback</h2>
    <div class="row"><div><span class="lbl">Crossfade</span>
      <span class="hint">Blend one song into the next over 2 seconds</span></div>
      <label class="sw"><input type="checkbox" data-pref="crossfade"><span></span></label></div>
    <div class="row"><div><span class="lbl">Volume leveling</span>
      <span class="hint">ReplayGain — evens out songs tagged with it</span></div>
      <label class="sw"><input type="checkbox" data-pref="replaygain"><span></span></label></div>
  </div>

  <div class="sec">
    <h2>Display</h2>
    <div class="row"><div><span class="lbl">Animations</span>
      <span class="hint">Screen transitions and Now Playing motion</span></div>
      <label class="sw"><input type="checkbox" data-pref="animations"><span></span></label></div>
    <div class="row"><span class="lbl">Home wallpaper</span>
      <select data-pref="wallpaper"></select></div>
  </div>

  <div class="sec">
    <h2>ListenBrainz</h2>
    <div class="state" id="lb-state">…</div>
    <div class="stack" id="lb-connect">
      <input type="text" id="lb-token" placeholder="User token from listenbrainz.org/settings"
             autocomplete="off" spellcheck="false">
      <div class="btns"><button class="btn" onclick="lbConnect()">Connect</button></div>
    </div>
    <div class="btns hide" id="lb-out" style="padding:4px 0 12px">
      <button class="btn ghost" onclick="lbSignOut()">Sign out</button></div>
    <div class="row"><div><span class="lbl">Username for mixes</span>
      <span class="hint">Smart Mixes read your ListenBrainz playlists and top songs —
      public data, no token needed</span></div>
      <input type="text" data-pref="listenbrainz_user" placeholder="username"
             style="width:140px" autocomplete="off" spellcheck="false"></div>
    <div class="row"><div><span class="lbl">Skip music-server songs</span>
      <span class="hint">Turn on if Navidrome already sends its plays to ListenBrainz,
      so they aren't counted twice</span></div>
      <label class="sw"><input type="checkbox" data-pref="listenbrainz_skip_server"><span></span></label></div>
    <div class="err2" id="lb-err"></div>
  </div>

  <div class="sec">
    <h2>Music server</h2>
    <div class="state" id="ss-state">…</div>
    <div class="stack" id="ss-connect">
      <input type="url" id="ss-url" placeholder="Server address, e.g. 192.168.1.20:4533"
             autocomplete="off" spellcheck="false">
      <input type="text" id="ss-user" placeholder="Username" autocomplete="off" spellcheck="false">
      <input type="password" id="ss-pass" placeholder="Password" autocomplete="off">
      <div class="btns"><button class="btn" onclick="ssConnect()">Connect</button></div>
    </div>
    <div class="btns hide" id="ss-actions" style="padding:4px 0 12px">
      <button class="btn" id="ss-sync" onclick="ssSync()">Sync now</button>
      <button class="btn ghost" onclick="ssSignOut()">Sign out</button></div>
    <div class="err2" id="ss-err"></div>
  </div>
</div>
<div class="toast" id="toast"></div>

<div class="drop hide" id="drop" onclick="document.getElementById('fi').click()">
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
<div class="stats hide" id="stats">Library: <span id="tc">…</span> tracks</div>
<button class="signout hide" id="so" onclick="signOut()">Forget token</button>

<script>
const drop=document.getElementById('drop'),
      fi=document.getElementById('fi'),
      bw=document.getElementById('bw'),
      bar=document.getElementById('bar'),
      st=document.getElementById('st'),
      gate=document.getElementById('gate'),
      gerr=document.getElementById('gerr'),
      stats=document.getElementById('stats'),
      so=document.getElementById('so');

const KEY='musi_token';
let token=localStorage.getItem(KEY)||'';
let timer=null;

// Every call carries the bearer token; a 401 drops us back to the gate.
async function api(path,opts){
  opts=opts||{};
  opts.headers=Object.assign({},opts.headers,{'Authorization':'Bearer '+token});
  const r=await fetch(path,opts);
  if(r.status===401){lock('Token rejected — check Settings → API on the device');throw new Error('unauthorized')}
  if(r.status===429){
    const s=r.headers.get('Retry-After')||'a while';
    lock('Too many wrong tokens — wait '+s+'s and try again');
    throw new Error('throttled');
  }
  return r;
}

let current='up';
function show(unlocked){
  gate.classList.toggle('hide',unlocked);
  document.getElementById('tabs').classList.toggle('hide',!unlocked);
  so.classList.toggle('hide',!unlocked);
  if(unlocked){tab(current)}
  else{
    ['drop','stats','settings'].forEach(id=>document.getElementById(id).classList.add('hide'));
    bw.style.display='none';st.textContent='';
  }
}

function tab(which){
  current=which;
  const up=which==='up';
  document.getElementById('tab-up').classList.toggle('on',up);
  document.getElementById('tab-set').classList.toggle('on',!up);
  drop.classList.toggle('hide',!up);
  stats.classList.toggle('hide',!up);
  st.classList.toggle('hide',!up);
  document.getElementById('settings').classList.toggle('hide',up);
  if(!up)loadSettings();
}

// ── settings ──────────────────────────────────────────────────────────────
function toast(msg){
  const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');
  clearTimeout(toast.h);toast.h=setTimeout(()=>t.classList.remove('show'),1800);
}

async function errorOf(r){
  if(r.status===423)return 'Storage is locked — unlock it in Settings → Power on the device';
  try{const d=await r.json();return d.error||('HTTP '+r.status)}catch(e){return 'HTTP '+r.status}
}

async function loadSettings(){
  try{
    const r=await api('/api/v1/settings');const d=await r.json();
    document.querySelectorAll('[data-pref]').forEach(el=>{
      const k=el.dataset.pref;
      if(el.tagName==='SELECT'){
        if(!el.options.length)(d.choices[k]||[]).forEach(c=>{
          const o=document.createElement('option');o.value=c;
          o.textContent=c.charAt(0).toUpperCase()+c.slice(1);el.appendChild(o)});
        el.value=d.values[k];
      }else if(el.type==='text')el.value=d.values[k]||'';
      else el.checked=!!d.values[k];
    });
  }catch(e){}
  loadListenBrainz();loadServer();
}

document.querySelectorAll('[data-pref]').forEach(el=>{
  el.addEventListener('change',async()=>{
    const k=el.dataset.pref,
          v=el.tagName==='SELECT'||el.type==='text'?el.value.trim():el.checked;
    try{
      const r=await api('/api/v1/settings',{method:'PATCH',
        headers:{'Content-Type':'application/json'},body:JSON.stringify({[k]:v})});
      if(!r.ok){toast(await errorOf(r));loadSettings();return}
      toast('Saved');
    }catch(e){}
  });
});

async function loadListenBrainz(){
  try{
    const d=await (await api('/api/v1/listenbrainz')).json();
    const s=document.getElementById('lb-state');
    s.innerHTML=d.connected
      ?'Scrobbling as <b>'+esc(d.user)+'</b>'+(d.queued?' · '+d.queued+' waiting to send':'')
      :'Not connected';
    document.getElementById('lb-connect').classList.toggle('hide',d.connected);
    document.getElementById('lb-out').classList.toggle('hide',!d.connected);
  }catch(e){}
}

async function lbConnect(){
  const e=document.getElementById('lb-err'),t=document.getElementById('lb-token');
  e.textContent='';
  if(!t.value.trim()){e.textContent='Paste your token first';return}
  try{
    const r=await api('/api/v1/listenbrainz',{method:'PUT',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({token:t.value.trim()})});
    if(!r.ok){e.textContent=await errorOf(r);return}
    t.value='';toast('ListenBrainz connected');loadListenBrainz();
  }catch(x){}
}

async function lbSignOut(){
  try{await api('/api/v1/listenbrainz',{method:'DELETE'});loadListenBrainz()}catch(x){}
}

let ssTimer=null;
function ago(ts){
  if(!ts)return 'never';
  const s=Math.max(0,Math.floor(Date.now()/1000-ts));
  if(s<60)return 'just now';if(s<3600)return Math.floor(s/60)+' min ago';
  if(s<86400)return Math.floor(s/3600)+' h ago';return Math.floor(s/86400)+' d ago';
}

async function loadServer(){
  try{
    const d=await (await api('/api/v1/subsonic')).json();
    const s=document.getElementById('ss-state'),j=d.sync||{};
    if(j.running){
      s.innerHTML='Syncing… <b>'+esc(j.phase||'')+'</b>'+(j.total?' '+j.done+'/'+j.total:'');
    }else if(d.configured){
      s.innerHTML='<b>'+esc(d.username)+'</b> on '+esc(d.url)+'<br>'+
        (d.track_count||0)+' songs · synced '+ago(d.last_sync)+
        (d.last_error?' · <span style="color:#ff5c8a">last sync failed: '+esc(d.last_error)+'</span>':'');
    }else s.textContent='Not connected — stream from Navidrome or any Subsonic server';
    document.getElementById('ss-connect').classList.toggle('hide',!!d.configured);
    document.getElementById('ss-actions').classList.toggle('hide',!d.configured);
    document.getElementById('ss-sync').disabled=!!j.running;
    if(j.running&&!ssTimer)ssTimer=setInterval(loadServer,2000);
    if(!j.running&&ssTimer){clearInterval(ssTimer);ssTimer=null}
  }catch(e){}
}

async function ssConnect(){
  const e=document.getElementById('ss-err');e.textContent='Checking login…';
  const body={url:document.getElementById('ss-url').value.trim(),
              username:document.getElementById('ss-user').value.trim(),
              password:document.getElementById('ss-pass').value};
  try{
    const r=await api('/api/v1/subsonic',{method:'PUT',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok){e.textContent=await errorOf(r);return}
    e.textContent='';document.getElementById('ss-pass').value='';
    toast('Connected — syncing');loadServer();
  }catch(x){e.textContent=''}
}

async function ssSync(){
  try{
    const r=await api('/api/v1/subsonic/sync',{method:'POST'});
    if(!r.ok&&r.status!==202){document.getElementById('ss-err').textContent=await errorOf(r);return}
    loadServer();
  }catch(x){}
}

async function ssSignOut(){
  if(!confirm('Sign out of the music server? Its songs are removed from musi.'))return;
  try{
    const r=await api('/api/v1/subsonic',{method:'DELETE'});
    if(!r.ok){document.getElementById('ss-err').textContent=await errorOf(r);return}
    loadServer();
  }catch(x){}
}

function esc(s){const d=document.createElement('div');d.textContent=s==null?'':String(s);return d.innerHTML}

function lock(msg){
  token='';localStorage.removeItem(KEY);
  if(timer){clearInterval(timer);timer=null}
  show(false);gerr.textContent=msg||'';
}

function signOut(){lock('')}

async function unlock(){
  try{
    const r=await api('/stats');
    const d=await r.json();
    document.getElementById('tc').textContent=d.tracks;
    localStorage.setItem(KEY,token);
    gerr.textContent='';
    show(true);
    if(!timer)timer=setInterval(fetchStats,5000);
  }catch(e){/* lock() already ran on 401 */}
}

function saveToken(){
  const v=document.getElementById('tok').value.trim();
  if(!v){gerr.textContent='Enter the token first';return}
  token=v;document.getElementById('tok').value='';
  unlock();
}

drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('over')});
drop.addEventListener('dragleave',()=>drop.classList.remove('over'));
drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('over');upload(e.dataTransfer.files)});
fi.addEventListener('change',()=>upload(fi.files));

async function upload(files){
  if(!files.length)return;
  bw.style.display='block';bar.style.width='0';
  let ok=0,skip=0,locked=false;
  try{
    for(let i=0;i<files.length;i++){
      const f=files[i];
      st.textContent='Uploading '+f.name+' ('+(i+1)+'/'+files.length+')…';
      const fd=new FormData();fd.append('file',f);
      const r=await api('/upload',{method:'POST',body:fd});
      if(r.status===423){locked=true;break}
      if(!r.ok)throw new Error('HTTP '+r.status+' on '+f.name);
      const d=await r.json();
      if(d.status==='ok')ok++;else skip++;
      bar.style.width=((i+1)/files.length*100)+'%';
    }
  }catch(e){
    // Never fail silently: a blank status bar looks identical to "nothing
    // happened" and hides real server errors (a 500 returns an HTML error
    // page, so r.json() throws and lands here).
    st.innerHTML='<span style="color:#ff5c8a">&#10007;</span> Upload failed &mdash; '+
                 (e && e.message ? e.message : 'connection lost');
    bw.style.display='none';
    return;
  }
  if(locked){
    st.innerHTML='<span style="color:#ff5c8a">✗</span> Storage is locked — unlock in Settings → Power on the device';
    return;
  }
  const msg=[];
  if(ok)msg.push(ok+' file'+(ok!==1?'s':'')+' added');
  if(skip)msg.push(skip+' already existed');
  st.innerHTML='<span style="color:#4dc87a">✓</span> '+msg.join(', ');
  fetchStats();
}

async function fetchStats(){
  try{const r=await api('/stats');const d=await r.json();
  document.getElementById('tc').textContent=d.tracks;}catch(e){}
}

show(false);
if(token)unlock();          // remembered token: verify it, then reveal the page
</script>
</body>
</html>
"""


# ── helpers ───────────────────────────────────────────────────────────────────

class RescanDebouncer:
    """Coalesce a burst of uploads into one library rescan 3 s after the last."""

    def __init__(self, music_root: Path, art_dir: Path, db_path: Path) -> None:
        self._music_root = music_root
        self._art_dir    = art_dir
        self._db_path    = db_path
        self._timer: threading.Timer | None = None

    def schedule(self) -> None:
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(
            3.0, _rescan, args=(self._music_root, self._art_dir, self._db_path),
        )
        self._timer.daemon = True
        self._timer.start()


def _rescan(music_root: Path, art_dir: Path, db_path: Path) -> None:
    try:
        from musi.library.db import open_db
        from musi.library.scanner import scan
        conn = open_db(db_path)
        scan(music_root=music_root, art_dir=art_dir, conn=conn)
        conn.close()
    except Exception:
        log.warning("rescan failed", exc_info=True)


def _storage_locked() -> bool:
    from musi.player import hardening
    return hardening.overlay_active()


def _locked_response():
    return jsonify(
        error="storage locked",
        hint="Unlock in Settings → Power on the device, then reboot",
    ), 423


def _mpd_update() -> None:
    """Ask MPD to refresh its own database after library file changes.
    Best-effort: no MPD (dev machine) is fine — mpd.conf also has
    auto_update, this just makes the refresh immediate."""
    try:
        from mpd import MPDClient
        client = MPDClient()
        client.timeout = 5
        client.connect("127.0.0.1", 6600)
        client.update()
        client.close()
        client.disconnect()
    except Exception:
        log.info("mpd db update skipped (no MPD?)")


def _mpd_apply(crossfade: "bool | None" = None, replaygain: "bool | None" = None) -> None:
    """Push playback settings to MPD (best-effort; the player re-applies the
    stored prefs at its next start anyway)."""
    from musi.player.prefs import CROSSFADE_S
    try:
        from mpd import MPDClient
        client = MPDClient()
        client.timeout = 5
        client.connect("127.0.0.1", 6600)
        if crossfade is not None:
            client.crossfade(CROSSFADE_S if crossfade else 0)
        if replaygain is not None:
            client.replay_gain_mode("auto" if replaygain else "off")
        client.close()
        client.disconnect()
    except Exception:
        log.info("mpd settings push skipped (no MPD?)")


def _uptime_s() -> int:
    """Device uptime; falls back to server-process uptime off-Pi."""
    try:
        return int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        return int(time.monotonic() - _STARTED)


def _cors_origins() -> "set[str]":
    """Allowed browser origins: built-in default + env + the api-origins file
    (one origin per line; lets the site domain change without a unit edit)."""
    import os
    raw = os.environ.get("MUSI_API_CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
    origins = {o.strip() for o in raw.split(",") if o.strip()}
    try:
        from musi.library.config import api_origins_path
        for line in api_origins_path().read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                origins.add(line.rstrip("/"))
    except OSError:
        pass
    return origins


class LoginThrottle:
    """Per-address lockout for wrong tokens.

    In-memory and per-process, which is the right scope here: one device, one
    API service, and a restart clearing the counters is not a weakness worth
    a database. Entries are keyed on the peer address; behind a proxy every
    request would share one key, so this must stay a directly-exposed server.
    """

    def __init__(self) -> None:
        self._fails: dict[str, tuple[int, float]] = {}   # addr -> (count, until)
        self._lock = threading.Lock()

    def retry_after(self, addr: str, now: float | None = None) -> float:
        """Seconds this address must wait, or 0.0 if it may try now."""
        now = time.monotonic() if now is None else now
        with self._lock:
            count, until = self._fails.get(addr, (0, 0.0))
            return max(0.0, until - now)

    def record_failure(self, addr: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._prune(now)
            count, _ = self._fails.get(addr, (0, 0.0))
            count += 1
            if count < FAIL_FREE:
                until = 0.0
            else:
                # The FAIL_FREE'th failure is itself the one that locks: the
                # gate checks retry_after *before* recording, so the caller
                # gets exactly FAIL_FREE tries and the next one is refused.
                delay = min(LOCK_BASE_S * (2 ** (count - FAIL_FREE)), LOCK_MAX_S)
                until = now + delay
            self._fails[addr] = (count, until)

    def record_success(self, addr: str) -> None:
        with self._lock:
            self._fails.pop(addr, None)

    def _prune(self, now: float) -> None:
        """Drop addresses idle for a day so the dict can't grow without bound."""
        stale = [a for a, (_, until) in self._fails.items()
                 if until and until + FAIL_TTL_S < now]
        for a in stale:
            del self._fails[a]


# ── app factory ───────────────────────────────────────────────────────────────

def create_app(
    music_root: Path,
    db_path: Path,
    art_dir: Path,
    *,
    token_provider: "Callable[[], str] | None" = None,
    cors_origins: "set[str] | None" = None,
) -> Flask:
    """Build the Flask app. ``token_provider`` is called per request so a
    regenerated token file takes effect without restarting the service."""
    get_token = token_provider or auth.load_token
    origins   = cors_origins if cors_origins is not None else _cors_origins()
    debouncer = RescanDebouncer(music_root, art_dir, db_path)
    throttle  = LoginThrottle()

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024  # 256 MB

    def _db() -> sqlite3.Connection:
        from musi.library.db import open_db
        return open_db(db_path)

    # ── auth + CORS gate for /api/v1 ──────────────────────────────────────────

    @app.before_request
    def _gate():
        if request.path in PUBLIC_PATHS:
            return None
        if request.path.startswith(LOCAL_PREFIX):
            if request.remote_addr in LOOPBACK:
                return None
            return jsonify(error="forbidden"), 403
        if request.method == "OPTIONS":       # CORS preflight carries no auth
            return app.make_default_options_response()

        addr = request.remote_addr or "?"
        wait = throttle.retry_after(addr)
        if wait > 0:
            resp = jsonify(error="too many attempts",
                           hint="wrong token — wait before trying again")
            return resp, 429, {"Retry-After": str(int(wait) + 1)}

        supplied = request.headers.get("Authorization", "")
        # Compared in canonical form: the token is typed by hand off the device
        # screen, so case and the display dash must not matter. `expected` is
        # checked for emptiness first — normalize() returns '' for junk, and
        # compare_digest('', '') is True, so a missing token file would
        # otherwise authenticate everyone.
        expected = auth.normalize(get_token())
        if not expected or not (supplied.startswith("Bearer ") and hmac.compare_digest(
            auth.normalize(supplied[7:]), expected
        )):
            throttle.record_failure(addr)
            return jsonify(error="unauthorized"), 401
        throttle.record_success(addr)
        # Storage lock (read-only overlay root) — refuse every write
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and _storage_locked():
            return _locked_response()
        return None

    @app.after_request
    def _cors(resp):
        origin = request.headers.get("Origin")
        if origin and origin in origins and request.path.startswith("/api/"):
            resp.headers["Access-Control-Allow-Origin"]  = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            resp.headers["Access-Control-Max-Age"]       = "600"
        return resp

    # ── legacy WiFi-transfer routes (LAN upload page) ─────────────────────────

    @app.route("/")
    def index():
        return _HTML

    def _handle_upload():
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
        debouncer.schedule()
        return jsonify(status="ok")

    @app.route("/upload", methods=["POST"])
    def upload():
        # Auth and the storage lock are both enforced centrally in _gate now
        # that this route is no longer exempt from it.
        return _handle_upload()

    @app.route("/stats")
    def stats():
        try:
            conn = _db()
            row  = conn.execute("SELECT COUNT(*) AS n FROM tracks").fetchone()
            conn.close()
            return jsonify(tracks=row["n"] if row else 0)
        except sqlite3.Error:
            return jsonify(tracks=0)

    # ── /api/v1 (authenticated JSON) ──────────────────────────────────────────

    # ── music server (Subsonic / Navidrome) ───────────────────────────────────

    @app.get("/local/subsonic/stream/<song_id>")
    def local_subsonic_stream(song_id: str):
        """MPD's way in to a server song: redirect to the server with fresh
        credentials. The stream URL MPD stores therefore holds no secret
        (library/remote.py)."""
        from musi.library import subsonic
        settings = subsonic.load_settings()
        if settings is None:
            return jsonify(error="no music server set up"), 404
        client = subsonic.Client.from_settings(settings)
        return redirect(client.stream_url(
            song_id, max_bitrate=int(settings.get("max_bitrate") or 0)), 302)

    def _subsonic_state() -> dict:
        from musi.library import subsonic
        from musi.library.subsonic_sync import job
        s = subsonic.load_settings() or {}
        return {
            "configured":  bool(s),
            "url":         s.get("url"),
            "username":    s.get("username"),
            "max_bitrate": int(s.get("max_bitrate") or 0),
            "last_sync":   s.get("last_sync"),
            "track_count": s.get("track_count", 0),
            "last_error":  s.get("last_error"),
            "sync": {"running": job.running, "phase": job.phase,
                     "done": job.done, "total": job.total,
                     "error": job.error or None, "stats": job.stats},
        }

    @app.get("/api/v1/subsonic")
    def api_subsonic_get():
        return jsonify(_subsonic_state())

    @app.put("/api/v1/subsonic")
    def api_subsonic_put():
        """Set up (or change) the server. The login is checked with a ping
        before anything is saved, then a first sync starts in the background."""
        from musi.library import subsonic
        from musi.library.subsonic_sync import job
        body = request.get_json(silent=True) or {}
        url, user = body.get("url", ""), body.get("username", "")
        password = body.get("password")
        old = subsonic.load_settings() or {}
        if password is None and old.get("url") and subsonic.normalize_url(url) == old["url"]:
            password = old.get("password", "")          # keep the saved one
        if not url or not user or password is None:
            return jsonify(error="url, username and password are required"), 400
        client = subsonic.Client(url, user, password)
        try:
            client.ping()
        except subsonic.SubsonicError as exc:
            return jsonify(error=str(exc)), 400
        subsonic.save_settings({
            "url": client.url, "username": user, "password": password,
            "max_bitrate": int(body.get("max_bitrate") or old.get("max_bitrate") or 0),
        })
        job.start(db_path, art_dir)
        return jsonify(_subsonic_state())

    @app.delete("/api/v1/subsonic")
    def api_subsonic_delete():
        """Sign out: forget the login and every server track."""
        from musi.library import subsonic
        from musi.library.subsonic_sync import remove_all
        subsonic.clear_settings()
        conn = _db()
        try:
            removed = remove_all(conn)
        finally:
            conn.close()
        return jsonify(removed=removed)

    @app.post("/api/v1/subsonic/sync")
    def api_subsonic_sync():
        from musi.library.subsonic_sync import job
        if not job.start(db_path, art_dir) and not job.running:
            return jsonify(error=job.error or "no music server set up"), 409
        return jsonify(_subsonic_state()), 202

    # ── player settings (the web page's Settings panel) ──────────────────────

    @app.get("/api/v1/settings")
    def api_settings_get():
        from musi.player import prefs
        prefs.refresh_if_changed()          # the player may have changed them
        return jsonify(
            values={k: prefs.get(k) for k in prefs.EDITABLE},
            choices={k: list(v) for k, v in prefs.EDITABLE.items() if isinstance(v, tuple)},
        )

    @app.patch("/api/v1/settings")
    def api_settings_patch():
        """Change player settings. The player picks the file change up within
        two seconds; crossfade and volume leveling are pushed to MPD here, so
        they take effect even if the UI isn't running."""
        from musi.player import prefs
        changes = request.get_json(silent=True)
        if not isinstance(changes, dict) or not changes:
            return jsonify(error="JSON object of settings required"), 400
        bad = sorted(k for k, v in changes.items() if not prefs.validate(k, v))
        if bad:
            return jsonify(error=f"invalid: {', '.join(bad)}"), 400
        prefs.refresh_if_changed()
        for k, v in changes.items():
            prefs.set(k, v)
        if "crossfade" in changes or "replaygain" in changes:
            _mpd_apply(crossfade=changes.get("crossfade"),
                       replaygain=changes.get("replaygain"))
        return jsonify(values={k: prefs.get(k) for k in prefs.EDITABLE})

    # ── ListenBrainz ──────────────────────────────────────────────────────────

    @app.get("/api/v1/listenbrainz")
    def api_listenbrainz_get():
        from musi.library import listenbrainz
        s = listenbrainz.load_settings()
        return jsonify(connected=bool(s), user=(s or {}).get("user"),
                       queued=listenbrainz.queued())

    @app.put("/api/v1/listenbrainz")
    def api_listenbrainz_put():
        """Save a user token — checked against ListenBrainz first."""
        from musi.library import listenbrainz
        token = ((request.get_json(silent=True) or {}).get("token") or "").strip()
        if not token:
            return jsonify(error="token is required"), 400
        try:
            user = listenbrainz.validate_token(token)
        except listenbrainz.ListenBrainzError as exc:
            return jsonify(error=str(exc)), 400
        listenbrainz.save_settings(token, user)
        return jsonify(connected=True, user=user)

    @app.delete("/api/v1/listenbrainz")
    def api_listenbrainz_delete():
        from musi.library import listenbrainz
        listenbrainz.clear_settings()
        return jsonify(connected=False)

    @app.get("/api/v1/status")
    def api_status():
        from musi.player import updater
        counts = {"artists": 0, "albums": 0, "tracks": 0}
        try:
            conn = _db()
            for key in counts:
                row = conn.execute(f"SELECT COUNT(*) AS n FROM {key}").fetchone()
                counts[key] = row["n"] if row else 0
            conn.close()
        except sqlite3.Error:
            pass
        try:
            usage = shutil.disk_usage(music_root)
            storage = {"total": usage.total, "free": usage.free}
        except OSError:
            storage = {"total": 0, "free": 0}
        return jsonify(
            version=updater.current_version(),
            uptime_s=_uptime_s(),
            storage=storage,
            counts=counts,
            storage_locked=_storage_locked(),
        )

    @app.get("/api/v1/albums")
    def api_albums():
        try:
            conn = _db()
            rows = conn.execute(
                """
                SELECT al.id, al.title, al.year, al.art_path,
                       ar.name AS artist, COUNT(t.id) AS track_count
                FROM albums al
                JOIN artists ar ON ar.id = al.artist_id
                LEFT JOIN tracks t ON t.album_id = al.id
                GROUP BY al.id
                ORDER BY ar.name COLLATE NOCASE, al.year, al.title COLLATE NOCASE
                """
            ).fetchall()
            conn.close()
        except sqlite3.Error:
            rows = []
        return jsonify(albums=[_album_json(r) for r in rows])

    @app.get("/api/v1/albums/<int:album_id>")
    def api_album(album_id: int):
        try:
            conn = _db()
            album = conn.execute(
                """
                SELECT al.id, al.title, al.year, al.art_path,
                       ar.name AS artist, COUNT(t.id) AS track_count
                FROM albums al
                JOIN artists ar ON ar.id = al.artist_id
                LEFT JOIN tracks t ON t.album_id = al.id
                WHERE al.id = ?
                GROUP BY al.id
                """,
                (album_id,),
            ).fetchone()
            if not album or album["id"] is None:
                conn.close()
                return jsonify(error="not found"), 404
            tracks = conn.execute(
                """
                SELECT id, title, track_number, disc_number, duration
                FROM tracks WHERE album_id = ?
                ORDER BY disc_number, track_number, title COLLATE NOCASE
                """,
                (album_id,),
            ).fetchall()
            conn.close()
        except sqlite3.Error:
            return jsonify(error="not found"), 404
        return jsonify(**_album_json(album), tracks=[dict(t) for t in tracks])

    @app.get("/api/v1/albums/<int:album_id>/art")
    def api_album_art(album_id: int):
        try:
            conn = _db()
            row = conn.execute(
                "SELECT art_path FROM albums WHERE id = ?", (album_id,)
            ).fetchone()
            conn.close()
        except sqlite3.Error:
            row = None
        if not row or not row["art_path"]:
            return jsonify(error="no art"), 404
        # Only ever serve files out of the art cache. Nothing writes an art_path
        # outside art_dir today, but this route would happily read any absolute
        # path the DB named — the delete path already guards this way.
        art_path = Path(row["art_path"])
        if art_path.parent != art_dir or not art_path.exists():
            return jsonify(error="no art"), 404
        return send_file(art_path, max_age=3600)

    # ── /api/v1 writes (auth + storage lock enforced in _gate) ────────────────

    def _prune_orphans(conn: sqlite3.Connection) -> None:
        conn.execute(
            "DELETE FROM albums WHERE id NOT IN (SELECT DISTINCT album_id FROM tracks)")
        conn.execute(
            "DELETE FROM artists WHERE id NOT IN (SELECT DISTINCT artist_id FROM tracks)")

    def _unlink_art_files(*paths: "str | None") -> None:
        """Delete art cache files (and the palette sidecar) inside art_dir only."""
        for p in paths:
            if not p:
                continue
            path = Path(p)
            if path.parent != art_dir:
                continue
            path.unlink(missing_ok=True)
            if path.name.endswith("_thumb.jpg"):
                (art_dir / path.name.replace("_thumb.jpg", "_palette.json")
                 ).unlink(missing_ok=True)

    @app.post("/api/v1/upload")
    def api_upload():
        return _handle_upload()

    @app.delete("/api/v1/tracks/<int:track_id>")
    def api_delete_track(track_id: int):
        conn = _db()
        row = conn.execute(
            "SELECT path FROM tracks WHERE id = ?", (track_id,)).fetchone()
        if not row:
            conn.close()
            return jsonify(error="not found"), 404
        if not remote.is_remote(row["path"]):    # server songs: nothing on disk
            Path(row["path"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        _prune_orphans(conn)
        conn.commit()
        conn.close()
        _mpd_update()
        return jsonify(status="ok")

    @app.delete("/api/v1/albums/<int:album_id>")
    def api_delete_album(album_id: int):
        conn = _db()
        album = conn.execute(
            "SELECT art_path, backdrop_path FROM albums WHERE id = ?",
            (album_id,)).fetchone()
        if not album:
            conn.close()
            return jsonify(error="not found"), 404
        tracks = conn.execute(
            "SELECT path FROM tracks WHERE album_id = ?", (album_id,)).fetchall()
        for t in tracks:
            if not remote.is_remote(t["path"]):
                Path(t["path"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM tracks WHERE album_id = ?", (album_id,))
        conn.execute("DELETE FROM albums WHERE id = ?", (album_id,))
        _prune_orphans(conn)
        conn.commit()
        conn.close()
        _unlink_art_files(album["art_path"], album["backdrop_path"])
        _mpd_update()
        return jsonify(status="ok", removed_tracks=len(tracks))

    @app.patch("/api/v1/tracks/<int:track_id>")
    def api_patch_track(track_id: int):
        from musi.library.tags import WRITABLE_TAGS, write_tags
        changes = request.get_json(silent=True)
        if not changes or not isinstance(changes, dict):
            return jsonify(error="JSON body with fields to change required"), 400
        unknown = set(changes) - set(WRITABLE_TAGS)
        if unknown:
            return jsonify(error=f"unknown fields: {', '.join(sorted(unknown))}",
                           allowed=sorted(WRITABLE_TAGS)), 400
        for field in ("year", "track_number"):
            if field in changes:
                try:
                    changes[field] = int(changes[field])
                except (TypeError, ValueError):
                    return jsonify(error=f"{field} must be an integer"), 400

        conn = _db()
        row = conn.execute(
            "SELECT path FROM tracks WHERE id = ?", (track_id,)).fetchone()
        if not row or not Path(row["path"]).exists():
            conn.close()
            return jsonify(error="not found"), 404
        try:
            write_tags(Path(row["path"]), changes)
        except Exception as exc:
            conn.close()
            return jsonify(error=f"tag write failed: {exc}"), 400

        # Mirror simple fields into the DB right away so reads are fresh;
        # artist/album regrouping is the rescan's job (file mtime changed).
        if "title" in changes:
            conn.execute("UPDATE tracks SET title = ? WHERE id = ?",
                         (changes["title"], track_id))
        if "track_number" in changes:
            conn.execute("UPDATE tracks SET track_number = ? WHERE id = ?",
                         (changes["track_number"], track_id))
        conn.commit()
        conn.close()
        debouncer.schedule()
        _mpd_update()
        return jsonify(status="ok", changed=changes)

    @app.put("/api/v1/albums/<int:album_id>/art")
    def api_put_art(album_id: int):
        from musi.library.art import override_art
        # Only consult files/form for multipart — touching them for any other
        # content type makes Flask consume the body and get_data() return b"".
        if request.mimetype == "multipart/form-data":
            f = request.files.get("file")
            image_bytes = f.read() if f else b""
        else:
            image_bytes = request.get_data()
        if not image_bytes:
            return jsonify(error="image required (multipart 'file' or raw body)"), 400

        conn = _db()
        album = conn.execute(
            """
            SELECT al.title, ar.name AS artist
            FROM albums al JOIN artists ar ON ar.id = al.artist_id
            WHERE al.id = ?
            """,
            (album_id,)).fetchone()
        if not album:
            conn.close()
            return jsonify(error="not found"), 404

        # Same key the scanner uses (artists.name == the tags' album_artist),
        # so we overwrite the exact cache files a rescan would reuse.
        album_key = f"{album['artist']}::{album['title']}"
        try:
            thumb, backdrop, palette = override_art(image_bytes, art_dir, album_key)
        except Exception:
            conn.close()
            return jsonify(error="invalid image"), 400
        import json as _json
        conn.execute(
            "UPDATE albums SET art_path = ?, backdrop_path = ?, palette = ? WHERE id = ?",
            (str(thumb), str(backdrop), _json.dumps(palette), album_id))
        conn.commit()
        conn.close()
        return jsonify(status="ok", art=f"/api/v1/albums/{album_id}/art")

    return app


def _album_json(row: sqlite3.Row) -> dict:
    return {
        "id":          row["id"],
        "title":       row["title"],
        "artist":      row["artist"],
        "year":        row["year"],
        "track_count": row["track_count"],
        "art":         f"/api/v1/albums/{row['id']}/art" if row["art_path"] else None,
    }
