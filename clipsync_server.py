#!/usr/bin/env python3
r"""
╔════════════════════════════════════════════════════╗
║   ClipSync Server  –  python3 stdlib only          ║
║   Start:  python3 clipsync_server.py               ║
╠════════════════════════════════════════════════════╣
║  Konfiguration via Umgebungsvariablen:             ║
║    CLIPSYNC_PORT   = 8765  (default)               ║
║    CLIPSYNC_TOKEN  = ""    (leer = kein Auth)      ║
║    CLIPSYNC_HOST   = "0.0.0.0"                     ║
║    CLIPSYNC_HTTPS  = "1"   (Standard, "0" für HTTP) ║
║    CLIPSYNC_CERT   = "clipsync.crt"  (eigenes Cert)║
║    CLIPSYNC_KEY    = "clipsync.key"  (eigener Key) ║
╠════════════════════════════════════════════════════╣
║  Beispiele:                                        ║
║    python3 clipsync_server.py                      ║
║    CLIPSYNC_HTTPS=1 CLIPSYNC_TOKEN=geheim \        ║
║      python3 clipsync_server.py                    ║
╚════════════════════════════════════════════════════╝

HTTPS: Beim ersten Start mit CLIPSYNC_HTTPS=1 wird automatisch
ein selbstsigniertes Zertifikat erzeugt (braucht: openssl im PATH).
Browser zeigt einmalig eine Warnung → "Trotzdem fortfahren" klicken
→ danach dauerhaft gespeichert.
"""

import os, json, time, mimetypes, base64, ssl, subprocess, socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PORT      = int(os.environ.get("CLIPSYNC_PORT", 8765))
HOST      = os.environ.get("CLIPSYNC_HOST", "0.0.0.0")
TOKEN     = os.environ.get("CLIPSYNC_TOKEN", "")
USE_HTTPS = os.environ.get("CLIPSYNC_HTTPS", "1").strip() not in ("0", "false", "no")
CERT_FILE = os.environ.get("CLIPSYNC_CERT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "clipsync.crt"))
KEY_FILE  = os.environ.get("CLIPSYNC_KEY",  os.path.join(os.path.dirname(os.path.abspath(__file__)), "clipsync.key"))
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clipsync_data.json")
MAX_ENTRIES = 100

# ── TLS / Certificate helpers ─────────────────────────────────────────────────

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def ensure_cert():
    """Generiert ein selbstsigniertes Zertifikat falls noch nicht vorhanden."""
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        print("  ✓ Zertifikat gefunden:", CERT_FILE)
        return True
    print("  → Erstelle selbstsigniertes Zertifikat...")
    local_ip = get_local_ip()
    hostname = socket.gethostname()
    cnf = f"""[req]
prompt             = no
default_bits       = 2048
distinguished_name = dn
x509_extensions    = v3_req
[dn]
CN = ClipSync
O  = HomeNetwork
[v3_req]
subjectAltName = @alt
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
[alt]
IP.1  = 127.0.0.1
IP.2  = {local_ip}
DNS.1 = localhost
DNS.2 = {hostname}
"""
    cnf_path = CERT_FILE.replace(".crt", ".cnf")
    try:
        with open(cnf_path, "w") as f:
            f.write(cnf)
        result = subprocess.run([
            "openssl", "req", "-x509", "-nodes",
            "-days", "3650",
            "-newkey", "rsa:2048",
            "-keyout", KEY_FILE,
            "-out", CERT_FILE,
            "-config", cnf_path,
        ], capture_output=True, text=True)
        os.unlink(cnf_path)
        if result.returncode != 0:
            print("  ✗ openssl Fehler:", result.stderr[:200])
            return False
        print(f"  ✓ Zertifikat erstellt: {CERT_FILE}")
        print(f"     Gueltig fuer: localhost, 127.0.0.1, {local_ip}, {hostname}")
        print(f"     Gueltigkeit: 10 Jahre")
        return True
    except FileNotFoundError:
        print("  ✗ openssl nicht gefunden. Installiere es oder setze CLIPSYNC_CERT/CLIPSYNC_KEY.")
        return False
    except Exception as e:
        print(f"  ✗ Zertifikat-Fehler: {e}")
        return False

def wrap_https(server):
    """Wraps den HTTPServer-Socket mit TLS."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    return server

# ── Data helpers ─────────────────────────────────────────────────────────────

def load():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save(entries):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(entries[:MAX_ENTRIES], f, ensure_ascii=True, indent=2)

def detect_type(content):
    c = content.strip()
    if c.startswith(("http://", "https://", "ftp://")):
        return "link"
    if "\n" in c and any(ch in c for ch in "{}[]();=>"):
        return "code"
    return "text"

def new_entry(content, label="", entry_type=None, filename=None):
    import random, string
    eid = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return {
        "id": eid,
        "content": content,
        "type": entry_type or detect_type(content),
        "label": label or filename or "",
        "filename": filename or "",
        "ts": int(time.time() * 1000),
    }

# ── Embedded HTML UI ──────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ClipSync</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=DM+Mono:ital,wght@0,300;0,500;1,300&display=swap');
  :root {
    --bg: #0b0b0d; --bg2: #0f0f13; --bg3: #141418;
    --border: #1f1f28; --border2: #2a2a35;
    --text: #ddd9d0; --text2: #888; --text3: #555;
    --accent: #b8f040; --accent2: #3a9eff; --accent3: #ff8a65;
    --code-color: #c3f0a0;
    --link-color: #3a9eff;
    --radius: 3px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'DM Mono', monospace; font-size: 13px; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

  /* Header */
  #header { display: flex; align-items: center; gap: 14px; padding: 12px 20px; background: var(--bg2); border-bottom: 1px solid var(--border); flex-shrink: 0; }
  #logo { font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 18px; letter-spacing: -0.5px; }
  #logo span { color: var(--accent); }
  #logo em { color: var(--accent2); font-style: normal; }
  #status { font-size: 10px; color: var(--text3); flex: 1; }
  #token-status { font-size: 10px; padding: 3px 10px; border: 1px solid var(--border2); color: var(--text3); }
  .btn { background: transparent; border: 1px solid var(--border2); color: var(--text2); padding: 5px 12px; font-size: 11px; cursor: pointer; font-family: inherit; transition: all .15s; }
  .btn:hover { border-color: var(--accent); color: var(--accent); }
  .btn.primary { background: var(--accent); color: #0b0b0d; border-color: var(--accent); font-weight: 600; }
  .btn.primary:hover { background: #d0ff60; }

  /* Layout */
  #main { display: flex; flex: 1; overflow: hidden; }

  /* Left panel */
  #left { width: 340px; min-width: 260px; border-right: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; }

  /* Input area */
  #input-area { padding: 14px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
  #label-input { width: 100%; background: transparent; border: none; border-bottom: 1px solid var(--border); color: var(--text2); font-size: 11px; padding: 3px 0 5px; outline: none; font-family: inherit; margin-bottom: 8px; }
  #label-input::placeholder { color: var(--text3); }
  #content-input { width: 100%; background: var(--bg); border: 1px solid var(--border); color: var(--text); font-size: 12px; padding: 10px; outline: none; font-family: inherit; resize: vertical; min-height: 90px; line-height: 1.5; transition: border-color .15s; }
  #content-input:focus { border-color: var(--border2); }
  #content-input::placeholder { color: var(--text3); }
  #input-actions { display: flex; gap: 8px; margin-top: 8px; align-items: center; }
  #hint { font-size: 10px; color: var(--text3); }

  /* Filter bar */
  #filter-bar { display: flex; border-bottom: 1px solid var(--border); background: var(--bg); flex-shrink: 0; }
  .filter-btn { flex: 1; background: transparent; border: none; border-bottom: 2px solid transparent; color: var(--text3); padding: 7px 4px; font-size: 10px; cursor: pointer; font-family: inherit; transition: all .15s; }
  .filter-btn.active { color: var(--accent); border-bottom-color: var(--accent); background: var(--bg3); }
  .filter-btn:hover:not(.active) { color: var(--text2); }

  /* Entry list */
  #list { flex: 1; overflow-y: auto; }
  #list::-webkit-scrollbar { width: 4px; } #list::-webkit-scrollbar-track { background: transparent; } #list::-webkit-scrollbar-thumb { background: var(--border2); }
  .entry { padding: 10px 14px; border-bottom: 1px solid var(--border); cursor: pointer; border-left: 3px solid transparent; transition: background .1s; }
  .entry:hover { background: var(--bg3); }
  .entry.selected { background: #13131a; border-left-color: var(--accent); }
  .entry-top { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
  .type-badge { font-size: 10px; font-weight: 600; min-width: 26px; }
  .type-text { color: var(--accent); }
  .type-code { color: #ff8a65; }
  .type-link { color: var(--accent2); }
  .type-image { color: #f0c040; }
  .type-file { color: #cc88ff; }
  .entry-label { font-size: 11px; color: var(--text2); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .entry-time { font-size: 10px; color: var(--text3); white-space: nowrap; }
  .entry-preview { font-size: 11px; color: #999; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }
  .entry-preview.link { color: var(--link-color); }
  .entry-img-thumb { height: 32px; width: 48px; object-fit: cover; border: 1px solid var(--border2); }
  .entry-img-row { display: flex; align-items: center; gap: 8px; }
  #empty { padding: 32px; text-align: center; color: var(--text3); font-size: 12px; line-height: 2; }

  /* Right panel - detail */
  #right { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  #detail-header { padding: 12px 20px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 10px; background: var(--bg2); flex-shrink: 0; }
  .tag { font-size: 10px; border: 1px solid var(--border2); color: var(--text3); padding: 2px 8px; }
  #detail-title { flex: 1; font-size: 11px; color: var(--text2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #detail-id { font-size: 10px; color: var(--text3); }
  #detail-body { flex: 1; overflow-y: auto; padding: 20px; }
  #detail-body::-webkit-scrollbar { width: 4px; } #detail-body::-webkit-scrollbar-thumb { background: var(--border2); }
  .detail-text { font-size: 13px; color: var(--text); line-height: 1.8; white-space: pre-wrap; word-break: break-word; }
  .detail-code { background: var(--bg); border: 1px solid var(--border); padding: 16px; font-size: 12px; color: var(--code-color); overflow-x: auto; white-space: pre; line-height: 1.6; }
  .detail-link a { color: var(--link-color); font-size: 14px; word-break: break-all; text-decoration: none; border-bottom: 1px solid #1a3a6a; }
  .detail-link a:hover { border-bottom-color: var(--link-color); }
  .detail-img img { max-width: 100%; max-height: 65vh; border: 1px solid var(--border2); }
  .detail-meta { margin-top: 20px; padding-top: 14px; border-top: 1px solid var(--border); display: flex; gap: 16px; flex-wrap: wrap; font-size: 10px; color: var(--text3); }
  #no-select { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; color: var(--text3); gap: 10px; }
  #no-select .icon { font-size: 36px; opacity: .3; }
  #no-select p { font-size: 11px; }

  /* Notifications */
  #notif { position: fixed; top: 16px; right: 20px; z-index: 9999; display: flex; flex-direction: column; gap: 6px; }
  .notif-msg { background: var(--bg3); border-left: 3px solid var(--accent); color: var(--text); padding: 8px 16px; font-size: 11px; font-family: inherit; animation: slideIn .2s ease; }
  .notif-msg.err { border-left-color: #ff5555; }
  @keyframes slideIn { from { opacity: 0; transform: translateX(20px); } to { opacity: 1; transform: none; } }

  /* Drop overlay */
  #drop-overlay { position: fixed; inset: 0; background: rgba(11,11,13,.85); border: 2px dashed var(--accent); display: none; align-items: center; justify-content: center; z-index: 8888; font-size: 20px; color: var(--accent); font-family: 'JetBrains Mono', monospace; }
  body.dragging #drop-overlay { display: flex; }
</style>
</head>
<body>

<div id="drop-overlay">↓ loslassen zum Einfügen</div>
<div id="notif"></div>

<div id="header">
  <div id="logo"><span>clip</span><em>sync</em></div>
  <div id="status">0 Einträge</div>
  <div id="token-status">🔓 kein auth</div>
  <button class="btn" onclick="toggleTerminal()" id="term-btn">$ hilfe</button>
</div>

<!-- Terminal Help Modal -->
<div id="term-modal" style="display:none; position:fixed; inset:0; background:rgba(11,11,13,.92); z-index:9000; overflow-y:auto; padding:40px 20px;">
  <div style="max-width:700px; margin:0 auto; background: var(--bg2); border: 1px solid var(--border2); padding: 28px;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <span style="font-family:'JetBrains Mono',monospace; font-weight:700; color:var(--accent); font-size:16px;">Terminal-Integration</span>
      <button class="btn" onclick="toggleTerminal()">✕ schließen</button>
    </div>
    <div id="term-content" style="font-size:12px; line-height:1.8; color: var(--text2);"></div>
  </div>
</div>

<div id="main">
  <div id="left">
    <div id="input-area">
      <input id="label-input" placeholder="Label (optional)" autocomplete="off">
      <textarea id="content-input" placeholder="Text, Code, Link einfügen… Strg+V für Bild, Drag & Drop für Dateien"></textarea>
      <div id="input-actions">
        <button class="btn primary" onclick="pushEntry()">PUSH ↑</button>
        <button class="btn" onclick="document.getElementById('file-input').click()" title="Datei hochladen">⬡ datei</button>
        <input id="file-input" type="file" style="display:none" onchange="handleFile(event)">
        <span id="hint">⌘↵ speichern</span>
      </div>
    </div>
    <div id="filter-bar">
      <button class="filter-btn active" data-f="all" onclick="setFilter('all')">alle</button>
      <button class="filter-btn" data-f="text" onclick="setFilter('text')">text</button>
      <button class="filter-btn" data-f="code" onclick="setFilter('code')">code</button>
      <button class="filter-btn" data-f="link" onclick="setFilter('link')">link</button>
      <button class="filter-btn" data-f="image" onclick="setFilter('image')">bild</button>
      <button class="filter-btn" data-f="file" onclick="setFilter('file')">datei</button>
    </div>
    <div id="list"></div>
  </div>

  <div id="right">
    <div id="no-select">
      <div class="icon">⬡</div>
      <p>Eintrag auswählen</p>
      <p style="font-size:10px; opacity:.5">Strg+V irgendwo → Bild direkt einfügen</p>
    </div>
    <div id="detail-view" style="display:none; flex-direction:column; height:100%;">
      <div id="detail-header">
        <span class="tag" id="detail-type">text</span>
        <span id="detail-title">–</span>
        <span id="detail-id" style="font-family:'JetBrains Mono',monospace;"></span>
        <button class="btn" id="copy-btn" onclick="copySelected()">kopieren</button>
        <button class="btn" id="download-btn" onclick="downloadEntry(entries.find(x=>x.id===selected))" style="display:none" title="Als Datei herunterladen">↓</button>
        <button class="btn" onclick="deleteSelected()" style="color:#744; border-color:#2a1a1a;">✕</button>
      </div>
      <div id="detail-body"></div>
    </div>
  </div>
</div>

<script>
// ── State ────────────────────────────────────────────────────────────────────
let entries = [];
let selected = null;
let filter = 'all';
const TOKEN = document.cookie.split(';').map(c => c.trim()).find(c => c.startsWith('cs_token='))?.split('=')[1] || '';

// ── API ──────────────────────────────────────────────────────────────────────
async function api(method, path, body) {
  const headers = { 'Content-Type': 'application/json' };
  if (TOKEN) headers['X-Token'] = TOKEN;
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function reload() {
  try {
    const data = await api('GET', '/api/entries');
    entries = data.entries;
    renderList();
    document.getElementById('status').textContent = `${entries.length} Einträge`;
  } catch (e) { notify('Ladefehler: ' + e.message, 'err'); }
}

// ── Rendering ────────────────────────────────────────────────────────────────
const TYPE_ICONS = { text:'¶', code:'</>', link:'↗', image:'⬚', file:'⬡' };
const TYPE_CLASS = { text:'type-text', code:'type-code', link:'type-link', image:'type-image', file:'type-file' };

function formatTime(ts) {
  const diff = (Date.now() - ts) / 1000;
  if (diff < 60) return 'gerade';
  if (diff < 3600) return `vor ${Math.floor(diff/60)}min`;
  if (diff < 86400) return `vor ${Math.floor(diff/3600)}h`;
  return new Date(ts).toLocaleDateString('de-DE');
}

function renderList() {
  const el = document.getElementById('list');
  const filtered = filter === 'all' ? entries : entries.filter(e => e.type === filter);
  if (!filtered.length) {
    el.innerHTML = '<div id="empty">Noch nichts hier.<br>Füge oben etwas ein.</div>';
    return;
  }
  el.innerHTML = filtered.map(e => `
    <div class="entry ${selected === e.id ? 'selected' : ''}" onclick="selectEntry('${e.id}')">
      <div class="entry-top">
        <span class="type-badge ${TYPE_CLASS[e.type]||'type-text'}">${TYPE_ICONS[e.type]||'¶'}</span>
        <span class="entry-label">${esc(e.label||'–')}</span>
        <span class="entry-time">${formatTime(e.ts)}</span>
      </div>
      ${e.type === 'image'
        ? `<div class="entry-img-row"><img class="entry-img-thumb" src="${e.content}" alt=""><span style="font-size:11px;color:var(--text3)">${esc(e.filename||'bild')}</span></div>`
        : `<div class="entry-preview ${e.type==='link'?'link':''}">${esc((e.content||'').slice(0,90))}</div>`
      }
    </div>`).join('');
}

function selectEntry(id) {
  selected = selected === id ? null : id;
  renderList();
  renderDetail();
}

function renderDetail() {
  const e = entries.find(x => x.id === selected);
  document.getElementById('no-select').style.display = e ? 'none' : 'flex';
  const dv = document.getElementById('detail-view');
  dv.style.display = e ? 'flex' : 'none';
  if (!e) return;

  document.getElementById('detail-type').textContent = e.type;
  document.getElementById('detail-title').textContent = e.label || e.filename || 'kein Label';
  document.getElementById('detail-id').textContent = '#' + e.id;
  // Dynamischer Button-Text + Download-Button je nach Typ
  const copyBtn = document.getElementById('copy-btn');
  copyBtn.textContent = updateCopyBtn(e);
  const dlBtn = document.getElementById('download-btn');
  const showDl = (e.type === 'image' || e.type === 'file');
  dlBtn.style.display = showDl ? '' : 'none';

  const body = document.getElementById('detail-body');
  let html = '';
  if (e.type === 'image') {
    html = `<div class="detail-img"><img src="${e.content}" alt="${esc(e.filename||'')}"></div>`;
  } else if (e.type === 'code') {
    html = `<pre class="detail-code">${esc(e.content)}</pre>`;
  } else if (e.type === 'link') {
    html = `<div class="detail-link"><a href="${esc(e.content)}" target="_blank" rel="noopener">${esc(e.content)}</a><div style="margin-top:8px;font-size:11px;color:var(--text3)">↗ öffnet im neuen Tab</div></div>`;
  } else {
    html = `<div class="detail-text">${esc(e.content)}</div>`;
  }
  html += `<div class="detail-meta">
    <span>ID: <code style="color:var(--text2)">${e.id}</code></span>
    <span>${new Date(e.ts).toLocaleString('de-DE')}</span>
    ${e.content ? `<span>${e.content.length} Zeichen</span>` : ''}
  </div>`;
  body.innerHTML = html;
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Actions ──────────────────────────────────────────────────────────────────
async function pushEntry(content, label, type, filename) {
  const c = content ?? document.getElementById('content-input').value.trim();
  const l = label ?? document.getElementById('label-input').value.trim();
  if (!c) { notify('Nichts eingegeben', 'err'); return; }
  try {
    await api('POST', '/api/push', { content: c, label: l, type, filename });
    document.getElementById('content-input').value = '';
    document.getElementById('label-input').value = '';
    notify('Gespeichert ✓');
    await reload();
    if (entries.length) selectEntry(entries[0].id);
  } catch(e) { notify('Fehler: ' + e.message, 'err'); }
}

async function deleteSelected() {
  if (!selected) return;
  try {
    await api('DELETE', `/api/entry/${selected}`);
    selected = null;
    notify('Gelöscht');
    await reload();
    renderDetail();
  } catch(e) { notify('Fehler: ' + e.message, 'err'); }
}

async function copySelected() {
  const e = entries.find(x => x.id === selected);
  if (!e) return;
  const btn = document.getElementById('copy-btn');

  const flash = (label) => {
    btn.textContent = label;
    btn.style.color = 'var(--accent)';
    btn.style.borderColor = 'var(--accent)';
    setTimeout(() => { btn.textContent = updateCopyBtn(e); btn.style.color = ''; btn.style.borderColor = ''; }, 1600);
  };

  if (e.type === 'image' && e.content && e.content.startsWith('data:image/')) {
    // Bild als ClipboardItem – direkt in andere Apps einfügbar
    try {
      const [header, b64] = e.content.split(',');
      const mime = header.match(/data:([^;]+)/)[1];
      const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
      const blob = new Blob([bytes], { type: mime });
      await navigator.clipboard.write([new ClipboardItem({ [mime]: blob })]);
      flash('✓ Bild kopiert');
    } catch (err) {
      // Fallback: dataUrl als Text
      await navigator.clipboard.writeText(e.content);
      flash('✓ als dataURL');
    }

  } else if ((e.type === 'file' || e.type === 'image') &&
             e.content && e.content.startsWith('[Binärdatei')) {
    // Binärdatei ohne Vorschau → Download auslösen
    downloadEntry(e);
    flash('↓ download');

  } else {
    // Text, Code, Link → normal als Text
    await navigator.clipboard.writeText(e.content || '');
    flash('✓ kopiert');
  }
}

function updateCopyBtn(e) {
  if (!e) return 'kopieren';
  if (e.type === 'image' && e.content && e.content.startsWith('data:image/')) return '⬚ bild kopieren';
  if (e.type === 'file') return '↓ download';
  return 'kopieren';
}

function downloadEntry(e) {
  if (!e) return;
  if (e.content && e.content.startsWith('data:')) {
    // dataURL → direkter Download
    const a = document.createElement('a');
    a.href = e.content;
    a.download = e.filename || e.label || 'download';
    a.click();
  } else if (e.type === 'image' && e.content && e.content.startsWith('data:image/')) {
    const a = document.createElement('a');
    a.href = e.content;
    a.download = e.filename || 'image.png';
    a.click();
  } else {
    // Text als Datei herunterladen
    const blob = new Blob([e.content || ''], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = e.filename || e.label || 'clipsync.txt';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

function setFilter(f) {
  filter = f;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.toggle('active', b.dataset.f === f));
  renderList();
}

// ── File / Image handling ────────────────────────────────────────────────────
function handleFile(evt) {
  const file = evt.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  if (file.type.startsWith('image/')) {
    reader.onload = ev => pushEntry(ev.target.result, file.name, 'image', file.name);
    reader.readAsDataURL(file);
  } else {
    reader.onload = ev => pushEntry(ev.target.result, file.name, 'file', file.name);
    reader.readAsText(file);
  }
  evt.target.value = '';
}

// Global paste → catch images
document.addEventListener('paste', e => {
  const items = e.clipboardData?.items || [];
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      e.preventDefault();
      const reader = new FileReader();
      reader.onload = ev => pushEntry(ev.target.result, 'screenshot', 'image', 'screenshot.png');
      reader.readAsDataURL(item.getAsFile());
      return;
    }
  }
});

// Drag & drop
document.addEventListener('dragover', e => { e.preventDefault(); document.body.classList.add('dragging'); });
document.addEventListener('dragleave', e => { if (!e.relatedTarget) document.body.classList.remove('dragging'); });
document.addEventListener('drop', e => {
  e.preventDefault();
  document.body.classList.remove('dragging');
  const file = e.dataTransfer.files[0];
  if (!file) return;
  if (isRenderableImage(file)) {
    const reader = new FileReader();
    reader.onload = ev => pushEntry(ev.target.result, file.name, 'image', file.name);
    reader.readAsDataURL(file);
  } else if (isRenderableText(file) && file.size <= MAX_TEXT_SIZE) {
    const reader = new FileReader();
    reader.onload = ev => pushEntry(ev.target.result, file.name, 'file', file.name);
    reader.readAsText(file);
  } else {
    notify(`Binärdatei: Metadaten gespeichert (${file.type || file.name})`, 'err');
    pushEntry(
      `[Binärdatei – keine Vorschau]\nName: ${file.name}\nGröße: ${(file.size/1024).toFixed(1)} KB\nTyp: ${file.type || 'unbekannt'}`,
      file.name, 'file', file.name
    );
  }
});

// Keyboard
document.getElementById('content-input').addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); pushEntry(); }
});

// ── Notifications ─────────────────────────────────────────────────────────────
function notify(msg, type = 'ok') {
  const el = document.createElement('div');
  el.className = 'notif-msg' + (type === 'err' ? ' err' : '');
  el.textContent = msg;
  document.getElementById('notif').appendChild(el);
  setTimeout(() => el.remove(), 2400);
}

// ── Token setup ───────────────────────────────────────────────────────────────
function checkToken() {
  const params = new URLSearchParams(location.search);
  const t = params.get('token');
  if (t) {
    document.cookie = `cs_token=${t}; path=/; max-age=31536000`;
    location.replace(location.pathname);
    return true;
  }
  return false;
}

// ── Terminal Help ─────────────────────────────────────────────────────────────
function toggleTerminal() {
  const m = document.getElementById('term-modal');
  if (m.style.display === 'none') {
    const host = location.host;
    const proto = location.protocol;
    const tokenLine = TOKEN ? `\n  CLIPSYNC_TOKEN="${TOKEN}"` : '';
    document.getElementById('term-content').innerHTML = `
<p style="color:var(--accent);margin-bottom:12px;">Füge folgendes in deine <code>~/.bashrc</code> ein:</p>
<pre style="background:var(--bg);border:1px solid var(--border);padding:14px;overflow-x:auto;font-size:11px;color:var(--code-color);line-height:1.7;"># ── ClipSync ───────────────────────────────────────────────
CLIPSYNC_HOST="${proto}//${host}"${tokenLine}

# ── pbpush: Text, Pipe oder Datei pushen ──────────────────
# pbpush "text"              → Text
# echo "text" | pbpush       → Text aus Pipe
# pbpush datei.txt           → Textdatei
# pbpush bild.png            → Bild (als dataURL)
# pbpush archiv.zip          → Binärdatei (Base64)
# pbpush archiv.zip "label"  → mit Label
pbpush() {
  python3 - "${'{'}{1:-}" "${'{'}{2:-}" "${'{'}{CLIPSYNC_HOST:-}" "${'{'}{CLIPSYNC_TOKEN:-}" << 'PYEOF'
import sys, os, json, mimetypes, base64, urllib.request, ssl

arg, label, host, token = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
ctx = ssl.create_default_context()
ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

def push(payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(host + '/api/push', data=data,
          headers={'Content-Type': 'application/json', 'X-Token': token})
    resp = json.loads(urllib.request.urlopen(req, context=ctx).read())
    print(f"OK  id={resp.get('id','?')}  type={resp.get('type','?')}")

if arg and os.path.isfile(arg):
    filename = os.path.basename(arg)
    mime, _ = mimetypes.guess_type(filename)
    mime = mime or 'application/octet-stream'
    with open(arg, 'rb') as f:
        raw = f.read()
    if mime.startswith('image/'):
        push({'content': f"data:{mime};base64,{base64.b64encode(raw).decode()}",
              'type': 'image', 'label': label or filename, 'filename': filename})
    elif mime.startswith('text/') or mime in ('application/json','application/xml','application/javascript'):
        code_exts = ('.py','.js','.ts','.sh','.json','.xml','.yaml','.yml','.sql','.css','.html')
        etype = 'code' if any(filename.endswith(e) for e in code_exts) else 'file'
        push({'content': raw.decode('utf-8', errors='replace'),
              'type': etype, 'label': label or filename, 'filename': filename})
    else:
        push({'content': f"data:{mime};base64,{base64.b64encode(raw).decode()}",
              'type': 'file', 'label': label or filename, 'filename': filename})
elif not sys.stdin.isatty() and not arg:
    push({'content': sys.stdin.read(), 'label': label})
elif arg:
    push({'content': arg, 'label': label})
else:
    print("Verwendung: pbpush 'text' | pbpush datei.zip | echo text | pbpush", file=sys.stderr)
    sys.exit(1)
PYEOF
}

# ── pbpull: Eintrag holen ─────────────────────────────────
# pbpull                   → letzten Eintrag auf stdout
# pbpull -o                → als Datei speichern (Originalname)
# pbpull -o datei.zip      → unter diesem Namen speichern
# pbpull -o ./ordner/      → in Ordner mit Originalname
# pbpull <id>              → bestimmten Eintrag auf stdout
# pbpull <id> -o [pfad]    → bestimmten Eintrag als Datei
pbpull() {
  python3 - "${'{'}{1:-}" "${'{'}{2:-}" "${'{'}{3:-}" "${'{'}{CLIPSYNC_HOST:-}" "${'{'}{CLIPSYNC_TOKEN:-}" << 'PYEOF'
import sys, os, json, base64, urllib.request, ssl

a1, a2, a3, host, token = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
ctx = ssl.create_default_context()
ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

def fetch(path):
    req = urllib.request.Request(host + path,
          headers={'X-Token': token} if token else {})
    return json.loads(urllib.request.urlopen(req, context=ctx).read())

# Argumente parsen
entry_id = None
outpath  = None
if a1 == '-o':
    outpath = a2 if a2 else '.'
elif a1 and not a1.startswith('-'):
    entry_id = a1
    if a2 == '-o':
        outpath = a3 if a3 else '.'

e        = fetch(f'/api/entry/{entry_id}' if entry_id else '/api/latest')
content  = e.get('content', '')
filename = e.get('filename') or e.get('label') or 'clipsync_download'
is_bin   = content.startswith('data:') and ';base64,' in content

if outpath is not None:
    if outpath == '.' or os.path.isdir(outpath):
        dest = os.path.join(outpath, filename)
    else:
        dest = outpath
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    if is_bin:
        raw = base64.b64decode(content.split(';base64,', 1)[1])
        with open(dest, 'wb') as f: f.write(raw)
        print(f"Gespeichert: {dest}  ({len(raw):,} Bytes)")
    else:
        with open(dest, 'w', encoding='utf-8') as f: f.write(content)
        print(f"Gespeichert: {dest}  ({len(content):,} Zeichen)")
else:
    if is_bin:
        print(f"[Binärdatei: {filename}]  zum Speichern: pbpull -o {filename}")
    else:
        print(content)
PYEOF
}

# ── pblast: Letzten Text-Eintrag in Clipboard ─────────────
pblast() {
  local out; out=$(pbpull)
  echo "$out"
  if command -v xclip &>/dev/null; then
    echo -n "$out" | xclip -selection clipboard && echo "→ Clipboard (xclip)"
  elif command -v pbcopy &>/dev/null; then
    echo -n "$out" | pbcopy && echo "→ Clipboard (pbcopy)"
  fi
}

# ── pblist: Übersicht aller Einträge ──────────────────────
pblist() {
  python3 - "${'{'}{CLIPSYNC_HOST:-}" "${'{'}{CLIPSYNC_TOKEN:-}" << 'PYEOF'
import sys, json, urllib.request, ssl, datetime
host, token = sys.argv[1], sys.argv[2]
ctx = ssl.create_default_context()
ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
req = urllib.request.Request(host + '/api/entries',
      headers={'X-Token': token} if token else {})
data = json.loads(urllib.request.urlopen(req, context=ctx).read())
print(f"{'ID':10}  {'Typ':6}  {'Größe':8}  {'Zeit':14}  Inhalt/Datei")
print('─' * 70)
for e in data.get('entries', [])[:30]:
    t  = e.get('type','?')
    c  = e.get('content','')
    fn = e.get('filename','') or e.get('label','')
    ts = datetime.datetime.fromtimestamp(e.get('ts',0)//1000).strftime('%d.%m %H:%M')
    sz = f"{len(c)//1024}KB" if len(c)>1024 else f"{len(c)}B"
    if c.startswith('data:') and ';base64,' in c:
        preview = f"[binary] {fn}"
    else:
        preview = (fn+': ' if fn else '') + c[:40].replace('\n',' ')
    print(f"{e['id']:10}  {t:6}  {sz:8}  {ts}  {preview}")
PYEOF
}
# ─────────────────────────────────────────────────────────</pre>
<p style="margin-top:14px; font-size:11px; color:var(--text3);">
  <strong style="color:var(--text2);">Nach dem Einfügen:</strong> <code>source ~/.bashrc</code><br><br>
  Dann direkt nutzen:<br>
  <code style="color:var(--accent);">pbpush "hallo welt"</code><br>
  <code style="color:var(--accent);">git log --oneline | pbpush</code><br>
  <code style="color:var(--accent);">pbpull</code>   → Text ausgeben<br>
  <code style="color:var(--accent);">pblast</code>   → Text ausgeben + in Clipboard<br>
  <code style="color:var(--accent);">pblist</code>   → alle Einträge anzeigen<br><br>
  <strong style="color:var(--text2);">Kein curl, kein wget</strong> – nur <code>python3</code> (stdlib).
  Funktioniert auch mit selbstsigniertem HTTPS-Zertifikat.
</p>`;
    m.style.display = 'block';
  } else {
    m.style.display = 'none';
  }
}
// ── Auth check display ────────────────────────────────────────────────────────
function updateAuthStatus() {
  const el = document.getElementById('token-status');
  if (TOKEN) { el.textContent = '🔒 auth aktiv'; el.style.color = 'var(--accent)'; el.style.borderColor = 'var(--accent)'; }
}

// ── Init ──────────────────────────────────────────────────────────────────────
checkToken();
updateAuthStatus();
reload();
setInterval(reload, 8000);  // auto-refresh alle 8s
</script>
</body>
</html>
"""

# ── HTTP Handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Minimales Logging
        if args and str(args[1]) not in ('200', '304'):
            print(f"  {args[0]} {args[1]}")

    def check_auth(self):
        if not TOKEN:
            return True
        return self.headers.get("X-Token") == TOKEN or \
               self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=True).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        # 50 MB limit (base64 images can be large)
        if length > 50 * 1024 * 1024:
            self.rfile.read(length)  # drain socket
            raise ValueError(f"Request too large: {length} bytes")
        raw = self.rfile.read(length)
        return json.loads(raw)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Token, Authorization")
        self.end_headers()

    def do_GET(self):
        try:
            self._do_GET_inner()
        except Exception as e:
            print(f"  ✗ GET error: {e}")
            try:
                self.send_json(500, {"error": str(e)})
            except:
                pass

    def _do_GET_inner(self):
        path = urlparse(self.path).path

        if path in ("/", "/index.html"):
            self.send_html(HTML)
            return

        if not self.check_auth():
            self.send_json(401, {"error": "unauthorized"})
            return

        if path == "/api/entries":
            entries = load()
            self.send_json(200, {"entries": entries, "count": len(entries)})

        elif path == "/api/latest":
            entries = load()
            if entries:
                self.send_json(200, entries[0])
            else:
                self.send_json(404, {"error": "empty"})

        elif path.startswith("/api/entry/"):
            eid = path.split("/")[-1]
            entries = load()
            entry = next((e for e in entries if e["id"] == eid), None)
            if entry:
                self.send_json(200, entry)
            else:
                self.send_json(404, {"error": "not found"})

        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        try:
            self._do_POST_inner()
        except Exception as e:
            print(f"  ✗ POST error: {e}")
            try:
                self.send_json(500, {"error": str(e)})
            except:
                pass

    def _do_POST_inner(self):
        if not self.check_auth():
            self.send_json(401, {"error": "unauthorized"})
            return

        path = urlparse(self.path).path

        if path == "/api/push":
            body = self.read_body()
            content = body.get("content", "")
            if isinstance(content, str):
                content = content.strip()
            entry_type = body.get("type")
            # Images have content = dataUrl (data:image/...) which is valid
            if not content:
                self.send_json(400, {"error": "content required"})
                return
            entry = new_entry(
                content,
                label=body.get("label", ""),
                entry_type=entry_type,
                filename=body.get("filename"),
            )
            entries = load()
            entries.insert(0, entry)
            save(entries)
            print(f"  + [{entry['type']:5}] {content[:60]}")
            self.send_json(201, {"ok": True, "id": entry["id"], "type": entry["type"]})

        else:
            self.send_json(404, {"error": "not found"})

    def do_DELETE(self):
        if not self.check_auth():
            self.send_json(401, {"error": "unauthorized"})
            return

        path = urlparse(self.path).path
        if path.startswith("/api/entry/"):
            eid = path.split("/")[-1]
            entries = load()
            before = len(entries)
            entries = [e for e in entries if e["id"] != eid]
            if len(entries) < before:
                save(entries)
                self.send_json(200, {"ok": True})
            else:
                self.send_json(404, {"error": "not found"})
        else:
            self.send_json(404, {"error": "not found"})


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    local_ip = get_local_ip()

    # HTTPS ist Standard – nur deaktivieren wenn explizit CLIPSYNC_HTTPS=0
    if USE_HTTPS:
        if not ensure_cert():
            print()
            print("  ┌─────────────────────────────────────────────────────┐")
            print("  │  ⚠  HTTPS-Zertifikat konnte nicht erstellt werden.  │")
            print("  │     Fallback auf HTTP.                               │")
            print("  │     Moderne Browser blockieren ggf. Features wie:   │")
            print("  │     • Clipboard API (Bilder kopieren)                │")
            print("  │     • Secure Cookies                                 │")
            print("  │     Empfehlung: openssl installieren und neu starten │")
            print("  └─────────────────────────────────────────────────────┘")
            print()
            USE_HTTPS = False

    proto = "https" if USE_HTTPS else "http"

    server = HTTPServer((HOST, PORT), Handler)
    server.socket.settimeout(None)  # no global timeout, handled per-request
    server.timeout = 30             # 30s per request max

    if USE_HTTPS:
        server = wrap_https(server)

    pad = lambda s, n: s + " " * max(0, n - len(s))
    url_local = f"{proto}://localhost:{PORT}"
    url_net   = f"{proto}://{local_ip}:{PORT}"

    BOLD  = "\033[1m"
    RESET = "\033[0m"
    WARN  = "\033[33m"

    print(f"""
{BOLD}╔══════════════════════════════════════════════════════╗
║             ClipSync läuft  ✓                        ║
╠══════════════════════════════════════════════════════╣
║  Lokal:    {pad(url_local, 42)}║
║  Im Netz:  {pad(url_net, 42)}║
║  Modus:    {pad(proto.upper() + (" (selbstsigniert)" if USE_HTTPS else ""), 42)}║
║  Auth:     {pad(("[aktiv] " + TOKEN[:16] + "…") if TOKEN else "kein Token", 42)}║
╠══════════════════════════════════════════════════════╣
║  Web-UI: $ hilfe  →  Bashrc-Snippet mit IP+Token    ║
║  Beenden: Strg+C                                     ║
╚══════════════════════════════════════════════════════╝{RESET}""")

    if USE_HTTPS:
        print(f"""  {WARN}Selbstsigniertes Zertifikat – einmalig im Browser bestätigen:
     Chrome:  Erweitert → Weiter zu {local_ip}
     Firefox: Erweitert → Risiko akzeptieren
     Safari:  Details → Website trotzdem besuchen{RESET}
""")
    else:
        print(f"""  {WARN}⚠  HTTP-Modus aktiv (kein HTTPS).
     Eingeschränkte Browser-Features: Clipboard-API, Secure Cookies.
     Zum Aktivieren: openssl installieren und Server neu starten.
     Oder manuell: CLIPSYNC_HTTPS=1 python3 clipsync_server.py{RESET}
""")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server gestoppt.")
