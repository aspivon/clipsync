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
- **HTTPS** standardmäßig aktiv, selbstsigniertes Zertifikat wird automatisch erstellt
- **Auth-Token** als zweite Verteidigungslinie gegen Gäste im Netz
- **Terminal-Integration** via `pbpush`, `pbpull`, `pblast`, `pblist` — nur `python3`
- **Binärdateien** (ZIP, PDF, Bilder, …) pushen und wieder als Datei pullen
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

# 2. Starten (HTTPS ist Standard, kein Auth)
python3 clipsync_server.py

# 3. Browser öffnen
# https://localhost:8765
# https://192.168.x.x:8765  (andere Rechner im LAN)
# → Browser-Warnung einmalig bestätigen (selbstsigniertes Zertifikat)
```

---

## Konfiguration

Alle Einstellungen werden per **Umgebungsvariable** gesetzt — keine Konfig-Datei nötig.

| Variable | Default | Beschreibung |
|---|---|---|
| `CLIPSYNC_PORT` | `8765` | Port des Servers |
| `CLIPSYNC_HOST` | `0.0.0.0` | Bind-Adresse (`127.0.0.1` für nur-lokal) |
| `CLIPSYNC_TOKEN` | *(leer)* | Auth-Token; leer = kein Auth |
| `CLIPSYNC_HTTPS` | `1` | HTTPS Standard; deaktivieren mit `0`, `false` oder `no` |
| `CLIPSYNC_CERT` | `clipsync.crt` | Pfad zum TLS-Zertifikat |
| `CLIPSYNC_KEY` | `clipsync.key` | Pfad zum privaten TLS-Schlüssel |

### Beispiele

```bash
# HTTPS mit Auth-Token (empfohlen, HTTPS ist Standard)
CLIPSYNC_TOKEN=meingeheimestoken python3 clipsync_server.py

# HTTP explizit erzwingen (nicht empfohlen – schränkt Browser-Features ein)
CLIPSYNC_HTTPS=0 python3 clipsync_server.py

# Anderen Port verwenden
CLIPSYNC_PORT=9000 python3 clipsync_server.py

# Nur lokal erreichbar (kein LAN-Zugriff)
CLIPSYNC_HOST=127.0.0.1 python3 clipsync_server.py

# Eigenes Zertifikat verwenden
CLIPSYNC_CERT=/etc/ssl/my.crt CLIPSYNC_KEY=/etc/ssl/my.key python3 clipsync_server.py
```

---

## HTTPS

HTTPS ist **standardmäßig aktiv**. Beim ersten Start wird automatisch ein **selbstsigniertes Zertifikat** für 10 Jahre erstellt — kein manueller `openssl`-Aufruf nötig.

Falls `openssl` nicht verfügbar ist, fällt der Server auf HTTP zurück und zeigt eine Warnung. HTTP schränkt Browser-Features ein (Clipboard-API für Bilder, Secure Cookies).

Das Zertifikat gilt für:
- `localhost` und `127.0.0.1`
- Die aktuelle LAN-IP des Rechners (z.B. `192.168.1.42`)
- Den Hostnamen des Rechners

Die Dateien `clipsync.crt` und `clipsync.key` werden neben dem Script gespeichert und beim nächsten Start wiederverwendet — keine erneute Generierung.

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

Das eingebaute **`$ hilfe`-Panel** in der Web-UI generiert ein Bashrc-Snippet mit der korrekten IP, dem Port und dem Token vorausgefüllt — fertig zum Einfügen.

### Setup

Den Block aus der Web-UI kopieren (`$ hilfe`-Button), in `~/.bashrc` (oder `~/.zshrc`) einfügen, dann:

```bash
source ~/.bashrc
```

Die zwei wichtigsten Variablen die gesetzt werden:

```bash
CLIPSYNC_HOST="https://192.168.1.42:8765"
CLIPSYNC_TOKEN="meintoken"   # leer lassen wenn kein Auth
```

---

## pbpush — Inhalte pushen

### Text

```bash
pbpush "das ist mein text"          # Text direkt
echo "hallo welt" | pbpush          # aus Pipe
git log --oneline | pbpush          # Ausgabe eines Befehls
cat /etc/hosts | pbpush             # Dateiinhalt als Text
pbpush "mein text" "mein label"     # mit Label
```

### Dateien und Binärdaten

```bash
pbpush bild.png                     # Bild → wird als image-Typ gespeichert
pbpush screenshot.jpg "vom laptop"  # Bild mit Label
pbpush archiv.zip                   # Binärdatei → Base64-kodiert gespeichert
pbpush dokument.pdf "Q3 Report"     # PDF mit Label
pbpush script.py                    # Textdatei → als code-Typ erkannt
pbpush config.yaml                  # Konfigurationsdatei
```

**Typ-Erkennung** erfolgt automatisch anhand MIME-Type und Dateiendung:

| Dateiart | Gespeicherter Typ |
|---|---|
| `.png`, `.jpg`, `.gif`, `.webp`, `.svg` | `image` |
| `.py`, `.js`, `.ts`, `.sh`, `.json`, `.yaml`, `.sql`, … | `code` |
| `.txt`, `.md`, `.csv`, `.log`, … | `file` (als Text) |
| `.zip`, `.pdf`, `.exe`, `.docx`, … | `file` (Base64) |

---

## pbpull — Inhalte holen

### Text ausgeben

```bash
pbpull                              # letzten Eintrag auf stdout
pbpull abc123def                    # bestimmten Eintrag (ID aus pblist)
```

Bei Binärdateien erscheint statt Zeichensalat ein Hinweis:
```
[Binärdatei: archiv.zip]  zum Speichern: pbpull -o archiv.zip
```

### Als Datei speichern

```bash
pbpull -o                           # letzten Eintrag speichern (Originalname)
pbpull -o meine_kopie.zip           # unter eigenem Namen speichern
pbpull -o ./downloads/              # in Ordner, Originalname beibehalten
pbpull abc123def -o                 # bestimmten Eintrag speichern (Originalname)
pbpull abc123def -o ./backup/       # bestimmten Eintrag in Ordner
pbpull abc123def -o neue_datei.zip  # bestimmten Eintrag umbenennen
```

Funktioniert für alle Typen — Text wird als UTF-8 gespeichert, Binärdateien werden aus Base64 dekodiert und byte-genau wiederhergestellt.

---

## pblast — Letzten Eintrag in Clipboard

```bash
pblast    # letzten Text-Eintrag ausgeben + direkt ins Clipboard kopieren
```

Nutzt `xclip` (Linux) oder `pbcopy` (macOS), falls vorhanden.

---

## pblist — Übersicht

```bash
pblist    # zeigt die letzten 30 Einträge mit ID, Typ, Größe, Zeit und Vorschau
```

Beispielausgabe:
```
ID          Typ     Größe     Zeit           Inhalt/Datei
──────────────────────────────────────────────────────────────────────
a1b2c3d4    image   48KB      14.02 09:31    screenshot.png
e5f6g7h8    code    2KB       14.02 09:28    deploy.sh: #!/bin/bash
i9j0k1l2    link    94B       14.02 09:15    https://example.com
m3n4o5p6    file    [binary]  13.02 17:44    [binary] archiv.zip
q7r8s9t0    text    38B       13.02 16:02    das ist mein text
```

Die **ID** aus `pblist` kann direkt in `pbpull <id>` und `pbpull <id> -o` verwendet werden.

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
  "content":  "text, dataURL (data:image/png;base64,...) oder Base64-Binärdaten",
  "label":    "optionales Label",
  "type":     "text|code|link|image|file",
  "filename": "dateiname.zip"
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

`clipsync_data.json`, `clipsync.crt` und `clipsync.key` gehören in die `.gitignore`:

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
