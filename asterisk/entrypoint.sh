#!/bin/sh
# Copy the baked-in configs over the package defaults, fill in the phone credentials, start Asterisk.
set -e

if [ -z "${PHONE_PASSWORD}" ]; then
  echo "ERROR: PHONE_PASSWORD is empty. Set it in your stack variables." >&2
  exit 1
fi
PHONE_EXT="${PHONE_EXT:-100}"
export PHONE_EXT PHONE_PASSWORD

SRC=/opt/asterisk-config
DST=/etc/asterisk
for f in asterisk.conf modules.conf extensions.conf rtp.conf logger.conf; do
  cp "$SRC/$f" "$DST/$f"
done
# Only substitute our own variables; leave Asterisk's ${...} alone.
envsubst '${PHONE_EXT} ${PHONE_PASSWORD}' < "$SRC/pjsip.conf.tmpl" > "$DST/pjsip.conf"

# Optional real phone number through VoIP.ms
if [ -n "${TRUNK_USER:-}" ]; then
  for v in TRUNK_PASSWORD TRUNK_SERVER TRUNK_NUMBER; do
    eval "val=\${$v:-}"
    if [ -z "$val" ]; then
      echo "ERROR: TRUNK_USER is set but $v is empty. Set it in .env, or clear TRUNK_USER." >&2
      exit 1
    fi
  done
  export TRUNK_USER TRUNK_PASSWORD TRUNK_SERVER TRUNK_NUMBER
  envsubst '${TRUNK_USER} ${TRUNK_PASSWORD} ${TRUNK_SERVER}' < "$SRC/pjsip_trunk.conf.tmpl" >> "$DST/pjsip.conf"
  envsubst '${TRUNK_NUMBER} ${PHONE_EXT}' < "$SRC/extensions_trunk.conf.tmpl" > "$DST/extensions_trunk.conf"
  echo "VoIP.ms trunk enabled: ${TRUNK_USER} @ ${TRUNK_SERVER}, number ${TRUNK_NUMBER}"
else
  printf '[outbound-trunk]\n[from-voipms]\n' > "$DST/extensions_trunk.conf"
  echo "No TRUNK_USER set: phone works for Claude only (no outside calls)"
fi

mkdir -p /spool/in /spool/tmp /spool/tts /spool/outgoing /spool/state /spool/requests
# claude-box runs as uid 1000 and must be able to create and delete files in these
chown 1000:1000 /spool /spool/in /spool/tmp /spool/tts /spool/outgoing /spool/state /spool/requests

echo "Starting Asterisk: extension ${PHONE_EXT} on UDP 5060"
exec /usr/sbin/asterisk -f -vvv
