#!/usr/bin/env bash
# Starts: Claude Code inside tmux, ttyd (browser view), and the phone watcher.
set -euo pipefail

mkdir -p /spool/{in,tmp,tts,outgoing,state,requests} /data/voices /data/hf "$HOME/.claude"

# 1) Claude Code lives in the persisted home folder so login and auto-updates survive rebuilds
if ! command -v claude >/dev/null 2>&1; then
  echo "[claude-box] Installing Claude Code..."
  curl -fsSL https://claude.ai/install.sh | bash
fi

# 2) Seed hook settings and phone instructions (never overwrites your own files)
if [ ! -f "$HOME/.claude/settings.json" ]; then
  cp /opt/claude-phone/templates/settings.json "$HOME/.claude/settings.json"
  echo "[claude-box] Wrote ~/.claude/settings.json with phone hooks"
elif ! grep -q "claude-phone/hook.py" "$HOME/.claude/settings.json"; then
  echo "[claude-box] WARNING: ~/.claude/settings.json exists but has no phone hooks."
  echo "             Merge in /opt/claude-phone/templates/settings.json or callbacks won't work."
fi
if [ ! -f "$HOME/.claude/CLAUDE.md" ]; then
  cp /opt/claude-phone/templates/CLAUDE.md "$HOME/.claude/CLAUDE.md"
fi

# 3) Claude Code in a tmux session called "claude" (restarts if you /exit)
if ! tmux has-session -t claude 2>/dev/null; then
  tmux new-session -d -s claude -x 220 -y 50 -c /workspace \
    "while true; do claude; echo; echo 'Claude exited. Restarting in 3s (Ctrl-C to stop)...'; sleep 3; done"
  tmux set -g mouse on
  tmux set -g history-limit 50000
fi

# 4) ttyd: watch (and type into) the same session from a browser
if [ -n "${TTYD_PASS:-}" ]; then
  # Own password prompt (use this only when NOT behind Authelia or another login proxy)
  ttyd -d 3 -p 7681 -W -c "${TTYD_USER:-claude}:${TTYD_PASS}" -t titleFixed="Claude Phone" \
    tmux attach -t claude &
else
  # No password of its own: login is handled by your reverse proxy (Authelia).
  # The compose file publishes no port, so only the proxy network can reach this.
  echo "[claude-box] TTYD_PASS is empty: browser view relies on your proxy's login"
  ttyd -d 3 -p 7681 -W -t titleFixed="Claude Phone" tmux attach -t claude &
fi

# 5) The watcher (foreground; its output is `docker logs claude-box`)
exec /opt/venv/bin/python -u /opt/claude-phone/watcher.py
