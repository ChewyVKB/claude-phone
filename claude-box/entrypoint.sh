#!/usr/bin/env bash
# Runs as root: make sure bind-mounted folders belong to uid 1000, then start as the claude user.
set -euo pipefail

mkdir -p /spool /home/claude /data /workspace
for d in /spool /home/claude /data; do
  [ "$(stat -c %u "$d")" = "1000" ] || chown -R 1000:1000 "$d"
done
# Workspace may be one of your own folders: only fix the top level if root owns it
[ "$(stat -c %u /workspace)" = "0" ] && chown 1000:1000 /workspace || true

# Browser view (ttyd, port 7681): who may connect.
#  - TRUSTED_PROXY_IP set: firewall the port so ONLY your reverse proxy can reach it
#    (the proxy enforces Authelia), so ttyd needs no password of its own.
#  - TTYD_PASS set: ttyd asks for its own password; open to the LAN.
#  - neither: ttyd listens inside the container only (use docker exec instead).
TTYD_IFACE=""
if [ -n "${TRUSTED_PROXY_IP:-}" ]; then
  if iptables -F INPUT 2>/dev/null \
     && iptables -A INPUT -p tcp --dport 7681 -s 127.0.0.1 -j ACCEPT \
     && iptables -A INPUT -p tcp --dport 7681 -s "${TRUSTED_PROXY_IP}" -j ACCEPT \
     && iptables -A INPUT -p tcp --dport 7681 -j DROP; then
    echo "[claude-box] Browser view: only ${TRUSTED_PROXY_IP} may connect to port 7681"
  else
    echo "[claude-box] ERROR: could not set firewall (is cap_add NET_ADMIN set?)." >&2
    echo "[claude-box]        Browser view disabled for safety." >&2
    TTYD_IFACE="lo"
  fi
elif [ -z "${TTYD_PASS:-}" ]; then
  echo "[claude-box] Neither TRUSTED_PROXY_IP nor TTYD_PASS set: browser view is local-only."
  TTYD_IFACE="lo"
fi

exec setpriv --reuid=1000 --regid=1000 --init-groups \
  env HOME=/home/claude USER=claude TTYD_IFACE="$TTYD_IFACE" /opt/claude-phone/start.sh
