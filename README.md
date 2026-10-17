# Claude Phone

Pick up a Polycom VVX, press a button, tell Claude Code what to do. When Claude has a question or needs permission, it rings you back.

```
VVX 501 ──SIP──► asterisk ──recording──► watcher ──Whisper──► tmux ──► Claude Code
   ▲                                                                       │
   └────── call file + Piper speech ◄──── watcher ◄──── hooks ◄────────────┘
```

## Deploy

Import `docker-compose.yml` from this repo into your stack dashboard (or run `docker compose up -d` next to it).
The images are built by GitHub Actions and published to GitHub's container registry on every push to `main`.

Required variables: `PHONE_PASSWORD` (the phone's SIP password) and `TTYD_PASS` (browser view login).
Optional: `PHONE_EXT`, `TTYD_USER`, `TZ`, `WHISPER_MODEL`, `WHISPER_HINT`, `PIPER_VOICE`,
`QUIET_HOURS`, `MIN_CALL_GAP`, `CALLBACK_MODE`, `PHONE_SESSION_HOURS`, `RING_ON_DONE`.

Then:

1. Open `http://<vm-ip>:7681` and log in to Claude Code (first run only).
2. Point the VVX at the VM: SIP server `<vm-ip>`, user/auth `100`, your `PHONE_PASSWORD`.
3. Speed dials: **2525** (Claude) and **\*26** (mute callbacks). **600** is an echo test.

## Using it

- **Talk to Claude:** dial 2525, wait for the beep, speak, hang up (or pause 3 s, or press #).
- **Claude asks a question:** rings as "Claude: question". Listen, answer after the beep, hang up.
- **Claude needs permission:** rings as "Claude: approve?". Press **1** to allow, **2** to deny.
- **Mute:** dial \*26. Dial again to unmute.

## Layout

| Path | What it does |
|---|---|
| `asterisk/` | PBX image: phone account (`config/pjsip.conf.tmpl`) and dialplan (`config/extensions.conf`) |
| `claude-box/app/watcher.py` | Whisper, Piper, typing into tmux, callback rules |
| `claude-box/app/hook.py` | Claude Code hooks that request callbacks |
| `claude-box/templates/` | Seeded into `~/.claude/` on first start (hooks + phone-mode instructions) |
| `.github/workflows/build.yml` | Builds and publishes both images |
| `App-Data/ClaudePhone/` | Created on the VM: shared spool, Claude login/home, models, workspace |

## Troubleshooting

- `docker exec claude-asterisk asterisk -rx "pjsip show endpoints"` → the phone should show as Avail.
- `docker logs -f claude-box` → what Whisper heard and why a callback did or didn't ring.
- Prompt went nowhere? A permission dialog was probably open; the watcher won't type over it.
