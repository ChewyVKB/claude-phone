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
# Only substitute our two variables; leave every other ${...} alone.
envsubst '${PHONE_EXT} ${PHONE_PASSWORD}' < "$SRC/pjsip.conf.tmpl" > "$DST/pjsip.conf"

mkdir -p /spool/in /spool/tmp /spool/tts /spool/outgoing /spool/state /spool/requests
# claude-box runs as uid 1000 and must be able to create and delete files in these
chown 1000:1000 /spool /spool/in /spool/tmp /spool/tts /spool/outgoing /spool/state /spool/requests

echo "Starting Asterisk: extension ${PHONE_EXT} on UDP 5060"
exec /usr/sbin/asterisk -f -vvv
