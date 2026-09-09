#!/usr/bin/env bash
# join-company.sh — put a headless profile onto a company's shared memory.
#
# The desktop Settings card does this over WebSocket for a signed-in user;
# on the host, for a daemon nobody is signed into, this does the same:
# stop the profile's daemon (the join needs the profile lock), run
# `zylch -p <uid> memory-join <key>` as the service user (preview echo,
# then merge + switch), start the daemon again.
#
# Usage:
#   sudo join-company.sh table                 # every profile: uid, email, key, store size
#   sudo join-company.sh <uid> <MEMORY_KEY>    # join <uid> to the memory <MEMORY_KEY> names
#
# The key comes from the profile you are joining TO (its `MEMORY_KEY` in
# the table). Joining is a merge: nothing this profile learned is lost,
# and its old store file is left on disk under ~mrcalld/.zylch/memory.
set -euo pipefail

SVC_USER=mrcalld
REPO="/home/$SVC_USER/mrcall-desktop"
VENV="$REPO/engine/venv"
PROFILES="/home/$SVC_USER/.zylch/profiles"
MEMORY="/home/$SVC_USER/.zylch/memory"
UNIT_PREFIX="zylch-server@"

[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }

env_value() { # env_value <file> <KEY>
  local line
  line=$(grep -E "^$2=" "$1" 2>/dev/null | tail -n1 || true)
  line=${line#*=}; line=${line%\"}; line=${line#\"}
  printf '%s' "$line"
}

if [ "${1:-}" = "table" ]; then
  printf '%-30s %-36s %-24s %s\n' UID EMAIL MEMORY_KEY STORE
  for d in "$PROFILES"/*/; do
    uid=$(basename "$d"); envf="$d/.env"
    [ -f "$envf" ] || continue
    email=$(env_value "$envf" EMAIL_ADDRESS); key=$(env_value "$envf" MEMORY_KEY)
    store="-"
    if [ -n "$key" ] && [ -f "$MEMORY/$key.db" ]; then
      n=$(sudo -u "$SVC_USER" sqlite3 "$MEMORY/$key.db" 'select count(*) from blobs' 2>/dev/null || echo '?')
      store="$n blobs"
    fi
    printf '%-30s %-36s %-24s %s\n' "$uid" "$email" "${key:-(none)}" "$store"
  done
  exit 0
fi

uid="${1:-}"; key="${2:-}"
[ -n "$uid" ] && [ -n "$key" ] || { echo "usage: $0 table | $0 <uid> <MEMORY_KEY>"; exit 2; }
[ -d "$PROFILES/$uid" ] || { echo "no profile dir for uid $uid under $PROFILES"; exit 2; }

unit="$UNIT_PREFIX$uid"
was_active=0
if systemctl is-active --quiet "$unit"; then was_active=1; fi

echo "== stopping $unit (the join needs the profile lock) =="
systemctl stop "$unit"
trap 'echo "== starting $unit =="; systemctl start "$unit"' EXIT

echo "== joining $uid to $key =="
sudo -u "$SVC_USER" env HOME="/home/$SVC_USER" "$VENV/bin/zylch" -p "$uid" memory-join --yes "$key"
