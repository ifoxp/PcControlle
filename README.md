**English** · [Українська](README.uk.md)

# PC Control

Control a Windows PC from your phone. An HTTP API plus background services,
wrapped in a tray icon with a real dashboard — and a separate Android app that
builds its own interface from whatever the PC says it can do.

## The idea worth explaining

The phone hardcodes nothing.

On connect it fetches `GET /manifest`, compares `MANIFEST_VERSION`, and redraws
its grid. Every command is a dict on the server with an `id`, a title, an icon,
an HTTP method and path — and a `widget` naming one of about twenty interaction
primitives the app knows how to render: button, toggle, slider with a value
getter, media view, text input, picker, touchpad, screen stream, process list,
power menu, file browser, log view.

So adding a new capability to the PC is **one dict entry**. No new APK, no store
release, nothing to install on the phone.

The manifest is also filtered per machine: the server computes what this
particular host can actually do and drops the rest. One monitor means no
"Monitors" tile; hibernate disabled means no hibernate button. The phone never
shows a control that would fail.

## Security

The port is exposed to the internet, so the protection is layered.

**TLS with fingerprint pinning.** A self-signed certificate is generated once.
The phone trusts it by SHA-256 fingerprint, delivered inside the pairing QR
code — which is stronger than a public CA here, because a compromised CA cannot
impersonate a certificate the client pins directly.

**Per-device bearer tokens.** Pairing takes a PIN exactly once and issues a
token unique to that phone. `devices.json` stores only the SHA-256 hash, so the
file is worthless if taken, and any single device can be revoked without
touching the others.

**Brute-force bans with escalation**, per-IP rate limits on every endpoint, and
optional replay protection using a nonce and timestamp.

One practical detail: streaming endpoints get their own, much higher rate-limit
bucket. The general limit was dropping touchpad mouse-move packets and causing
visible lag — the right fix was a separate bucket, not a weaker limit
everywhere.

## Background services

**Photo sorter.** Uses a local Ollama vision model to classify what lands in
your camera folder, moves screenshots and short clips to trash, and syncs the
rest. Runs offline, on your own machine.

**Per-app volume.** Every application is tied to the master volume by a saved
offset. The interesting part is telling a deliberate change from an artefact:
the Windows mixer sometimes shifts a level on its own. A new offset is stored
only when the change is confirmed — either a drag, where the level moves the
same direction for several ticks, or a jump of at least 8% that holds. An
unconfirmed small jump is treated as noise and rolled back.

**Presence-based auto-shutdown** and a task tracker round it out.

## Running it

```bash
pip install -r requirements.txt
python main.py
```

The API token is generated on first run and stored in `.env`, which is not
committed. `config.json` holds the non-secret switches — port, thresholds,
sorter options.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `/` | health check, no token |
| `/manifest` | what this machine can do |
| `/pair` (POST) | exchange a PIN for a per-device token |
| `/devices` | paired devices |
| `/shutdown`, `/shutdown_timer?minutes=N` | power |
| `/toggle_monitor` | switch between one and two monitors |
| `/screenshot` | PNG of the main monitor |
| `/volume?level=0-100`, `/volume_get` | volume |
| `/sorter/run`, `/sorter/status` | photo sorter |

All protected requests take `Authorization: Bearer <token>`.

## Mobile app

A separate Flet application, built to an APK. Because it renders from the
manifest, it rarely needs rebuilding — the PC side is where features are added.

---

**Chekaliuk Dmytro** · [@ifoxp](https://github.com/ifoxp) ·
[ifoxp.top](https://ifoxp.top) · Telegram [@ifoxp](https://t.me/ifoxp) ·
Discord `ifoxp`
