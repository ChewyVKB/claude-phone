#!/usr/bin/env bash
# Runs as root: make sure bind-mounted folders belong to uid 1000, then start as the claude user.
set -euo pipefail

mkdir -p /spool /home/claude /data /workspace
for d in /spool /home/claude /data; do
  [ "$(stat -c %u "$d")" = "1000" ] || chown -R 1000:1000 "$d"
done
# Workspace may be one of your own folders: only fix the top level if root owns it
[ "$(stat -c %u /workspace)" = "0" ] && chown 1000:1000 /workspace || true

exec setpriv --reuid=1000 --regid=1000 --init-groups \
  env HOME=/home/claude USER=claude /opt/claude-phone/start.sh
