# ClipSync

Ein schlanker, selbst gehosteter Clipboard-Server für den Heimnetz-Einsatz. Texte, Code-Schnipsel, Links, Screenshots und Dateien zwischen Rechnern austauschen — über den Browser oder direkt aus dem Terminal, **ohne curl, ohne externe Dependencies, nur Python 3 stdlib**.

```
┌─────────────────────────────────────────────────┐
│  Rechner A          ←──────→       Rechner B    │
│  python3            LAN/HTTPS      Browser /    │
│  clipsync_server.py                Terminal     │
└─────────────────────────────────────────────────┘
```

---

## Features

- **Web-UI** mit Live-Vorschau, Typ-Erkennung (Text, Code, Link, Bild, Datei) und Filter
- **Screenshots** direkt per Strg+V in die Seite einfügen
- **Drag & Drop** für Dateien und Bilder
- **HTTPS** mit automatisch generiertem selbstsigniertem Zertifikat (via `openssl`)
- **Auth-Token** als zweite Verteidigungslinie gegen Gäste im Netz
- **Terminal-Integration** via `pbpush`, `pbpull`, `pblast`, `pblist` — nur `python3`
- **Auto-Refresh** der Web-UI alle 8 Sekunden
- Keine Datenbank, keine Dependencies — eine einzige `.py`-Datei, Daten in `clipsync_data.json`

---

## Voraussetzungen

| Was | Warum |
|---|---|
| Python 3.6+ | Läuft der Server |
| `openssl` im PATH | Nur für HTTPS / automatisches Zertifikat |
| `xclip` (Linux) oder `pbcopy` (macOS) | Nur für `pblast` (direkt in Clipboard) |

---

## Quickstart

```bash
# 1. Herunterladen
git clone https://github.com/DEIN-USER/clipsync.git
cd clipsync

# 2. Starten (HTTP, kein Auth – für reines Heimnetz ok)
python3 clipsync_server.py

# 3. Browser öffnen
# http://localhost:8765
# http://192.168.x.x:8765  (andere Rechner im LAN)
```

---

## Konfiguration

Alle Einstellungen werden per **Umgebungsvariable** gesetzt — keine Konfig-Datei nötig.

| Variable | Default | Beschreibung |
|---|---|---|
| `CLIPSYNC_PORT` | `8765` | Port des Servers |
| `CLIPSYNC_HOST` | `0.0.0.0` | Bind-Adresse (`127.0.0.1` für nur-lokal) |
| `CLIPSYNC_TOKEN` | *(leer)* | Auth-Token; leer = kein Auth |
| `CLIPSYNC_HTTPS` | `0` | HTTPS aktivieren: `1`, `true` oder `yes` |
| `CLIPSYNC_CERT` | `clipsync.crt` | Pfad zum TLS-Zertifikat |
| `CLIPSYNC_KEY` | `clipsync.key` | Pfad zum privaten TLS-Schlüssel |

### Beispiele

```bash
# HTTP, kein Auth
python3 clipsync_server.py

# HTTPS mit Auth-Token
CLIPSYNC_HTTPS=1 CLIPSYNC_TOKEN=meingeheimestoken python3 clipsync_server.py

# Anderen Port verwenden
CLIPSYNC_PORT=9000 python3 clipsync_server.py

# Nur lokal erreichbar (kein LAN-Zugriff)
CLIPSYNC_HOST=127.0.0.1 python3 clipsync_server.py

# Eigenes Zertifikat verwenden
CLIPSYNC_HTTPS=1 CLIPSYNC_CERT=/etc/ssl/my.crt CLIPSYNC_KEY=/etc/ssl/my.key \
  python3 clipsync_server.py
```

---

## HTTPS

Beim ersten Start mit `CLIPSYNC_HTTPS=1` wird automatisch ein **selbstsigniertes Zertifikat** für 10 Jahre erstellt — kein manueller `openssl`-Aufruf nötig.

Das Zertifikat gilt für:
- `localhost`
- `127.0.0.1`
- Die aktuelle LAN-IP des Rechners (z.B. `192.168.1.42`)
- Den Hostnamen des Rechners

Die Dateien `clipsync.crt` und `clipsync.key` werden neben dem Script gespeichert und beim nächsten Start wiederverwendet.

### Browser-Warnung (einmalig)

Da das Zertifikat selbstsigniert ist, zeigt der Browser beim ersten Aufruf eine Warnung:

| Browser | Klickpfad |
|---|---|
| **Chrome** | „Erweitert" → „Weiter zu 192.168.x.x" |
| **Firefox** | „Erweitert" → „Risiko akzeptieren und fortfahren" |
| **Safari** | „Details einblenden" → „Diese Website trotzdem besuchen" |

Nach einmaliger Bestätigung ist die Ausnahme dauerhaft gespeichert.

---

## Terminal-Integration

Das eingebaute **`$ hilfe`-Panel** in der Web-UI generiert ein Bashrc-Snippet mit der korrekten IP, dem Port und dem Token — fertig zum Einfügen.

### Manuell einrichten

In `~/.bashrc` (oder `~/.zshrc`) einfügen:

```bash
# ── ClipSync ────────────────────────────────────────────────
CLIPSYNC_HOST="https://192.168.1.42:8765"   # oder http://
CLIPSYNC_TOKEN="meintoken"                  # leer lassen wenn kein Auth

_cs_request() {
  local url="$CLIPSYNC_HOST$1"
  python3 -c "
import urllib.request, urllib.error, json, ssl, os, sys
url  = sys.argv[1]
meth = sys.argv[2] if len(sys.argv) > 2 else 'GET'
body = sys.argv[3].encode() if len(sys.argv) > 3 else None
ctx  = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode    = ssl.CERT_NONE          # ok fuer selbstsigniertes LAN-Cert
req = urllib.request.Request(url, data=body, method=meth,
      headers={'Content-Type': 'application/json',
               'X-Token': os.environ.get('CLIPSYNC_TOKEN','')})
try:
    resp = urllib.request.urlopen(req, context=ctx)
    print(resp.read().decode())
except urllib.error.HTTPError as e:
    print('HTTP', e.code, e.reason, file=sys.stderr)
" "$url" "$@"
}

# Letzten Eintrag ausgeben
pbpull() {
  python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
print(data.get('content',''))
" <<< "$(_cs_request /api/latest)"
}

# Letzten Eintrag ausgeben UND in Clipboard kopieren
pblast() {
  local content
  content=$(pbpull)
  echo "$content"
  if command -v xclip &>/dev/null; then
    echo -n "$content" | xclip -selection clipboard && echo "→ Clipboard (xclip)"
  elif command -v pbcopy &>/dev/null; then
    echo -n "$content" | pbcopy && echo "→ Clipboard (pbcopy)"
  else
    echo "(xclip/pbcopy nicht gefunden)" >&2
  fi
}

# Eintrag pushen
# Verwendung:  pbpush "text"   ODER   echo "text" | pbpush
pbpush() {
  local content="${1:-$(cat)}"
  local result
  result=$(_cs_request /api/push POST "$(python3 -c "
import json,sys
print(json.dumps({'content':sys.argv[1]}))
" "$content")")
  python3 -c "
import json,sys
d=json.loads(sys.argv[1])
print('OK:', d.get('id','?'), '('+d.get('type','?')+')')
" "$result"
}

# Alle Einträge auflisten (letzte 20)
pblist() {
  python3 -c "
import json, sys, os
data  = json.loads(sys.stdin.read())
entries = data.get('entries', [])[:20]
for e in entries:
    t     = e.get('type','?')
    label = e.get('label','') or (e.get('content','')[:50].replace('\n',' '))
    ts    = e.get('ts', 0) // 1000
    print(f\"{e['id']}  [{t:5}]  {label}\")
" <<< "$(_cs_request /api/entries)"
}
# ─────────────────────────────────────────────────────────────
```

Nach dem Einfügen:

```bash
source ~/.bashrc
```

### Verwendung

```bash
# Text pushen
pbpush "das ist mein text"

# Pipe pushen
git log --oneline | pbpush
cat /etc/hosts | pbpush
pwd | pbpush

# Letzten Eintrag holen
pbpull               # nur Ausgabe im Terminal
pblast               # Ausgabe + direkt in Clipboard

# Alle Einträge auflisten
pblist
```

> **Kein curl, kein wget** — alle Funktionen nutzen ausschließlich `python3` aus der Standardbibliothek.

---

## API

Der Server stellt eine minimalistische REST-API bereit. Auth via `X-Token`-Header (wenn Token gesetzt).

| Methode | Pfad | Beschreibung |
|---|---|---|
| `GET` | `/api/entries` | Alle Einträge (JSON-Array) |
| `GET` | `/api/latest` | Neuester Eintrag |
| `GET` | `/api/entry/:id` | Einzelner Eintrag per ID |
| `POST` | `/api/push` | Neuen Eintrag anlegen |
| `DELETE` | `/api/entry/:id` | Eintrag löschen |

**POST `/api/push` — Request-Body:**
```json
{
  "content": "mein text oder data:image/png;base64,...",
  "label":   "optionales Label",
  "type":    "text|code|link|image|file",
  "filename": "dateiname.txt"
}
```

---

## Autostart (Linux systemd)

Damit ClipSync beim Booten automatisch startet:

```ini
# /etc/systemd/system/clipsync.service
[Unit]
Description=ClipSync Clipboard Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/clipsync/clipsync_server.py
WorkingDirectory=/opt/clipsync
Restart=always
RestartSec=5
Environment=CLIPSYNC_HTTPS=1
Environment=CLIPSYNC_TOKEN=meintoken

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now clipsync
sudo systemctl status clipsync
```

---

## Dateien

```
clipsync/
├── clipsync_server.py   # Der Server (alles in einer Datei)
├── clipsync_data.json   # Wird automatisch erstellt (Einträge)
├── clipsync.crt         # Wird automatisch erstellt (HTTPS-Zertifikat)
├── clipsync.key         # Wird automatisch erstellt (privater Schlüssel)
└── README.md
```

`clipsync_data.json`, `clipsync.crt` und `clipsync.key` sollten in `.gitignore` stehen:

```gitignore
clipsync_data.json
clipsync.crt
clipsync.key
```

---

## Sicherheitshinweise

- ClipSync ist für den **Heimnetz-Einsatz** konzipiert, nicht als öffentlich erreichbarer Service.
- Der Auth-Token schützt gegen ungebetene Zugriffe (z.B. Gäste im WLAN), ist aber kein Ersatz für echte Authentifizierung.
- Das selbstsignierte Zertifikat verhindert passives Mitlesen im LAN — ein echter CA-signierter Cert (z.B. via Let's Encrypt + Reverse Proxy) bietet mehr Schutz für öffentliche Deployments.
- Wer den Server über das Internet erreichbar machen will: VPN oder SSH-Tunnel sind die bessere Wahl.

---

## Lizenz

MIT — mach damit, was du willst.
