#!/usr/bin/env bash
# tenant-helper.sh — the ONE root-owned entry point that creates, joins and
# deletes per-profile Unix identities on a hosted engine host.
#
# Installed by update-daemons.sh to /usr/local/sbin/mrcall-tenant with
# `install -m 750`; the checkout copy is never executed and the sudoers rule
# (for provisiond, later) names the installed path only — the checkout is
# writable by `mrcalld`, and a rule on it would be a root escalation from a
# network-facing daemon. Plan M2.3/M2.4 of
# docs/execution-plans/2026-09-29-toward-sandbox.md.
#
# Usage (root):
#   mrcall-tenant create <uid>                 # user, key file, drop-in, runtime dir, subdirs, chown, company group+dir
#   mrcall-tenant join   <uid> <company-group> # add the user to a second company group (during a join)
#   mrcall-tenant unjoin <uid> <company-group> # remove it (after the join finished)
#   mrcall-tenant delete <uid> [--last-holder] # stop, offboard (as the tenant user), remove everything
#   mrcall-tenant names  <uid>                 # print the derived names, change nothing
#
# Every verb is idempotent: a reconcile trigger on a half-written profile
# converges on the next run. Names never carry the uid or the key:
# user `mc-<sha256(uid)[:12]>`, group `mc-c-<sha256(key)[:12]>` (see
# zylch/memory/tenant_names.py — this script derives them the same way).
set -euo pipefail

SVC_USER=mrcalld
ROOT="/home/$SVC_USER"
ZHOME="$ROOT/.zylch"
PROFILES="$ZHOME/profiles"
MEMORY="$ZHOME/memory"
REPO="$ROOT/mrcall-desktop"
VENV="$REPO/engine/venv"
KEYS_DIR=/etc/mrcalld/keys
TABLE=/etc/mrcalld/tenants.tsv          # root-only: uid <TAB> user <TAB> created-at
DROPIN_DIR=/etc/systemd/system
TMPFILES_DIR=/etc/tmpfiles.d
RUN_ROOT=/run/mrcalld
PROXY_GROUP=caddy
UNIT_PREFIX="zylch-server@"

[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }

log() { echo "[tenant] $*"; }
die() { echo "[tenant] ERROR: $*" >&2; exit 2; }

# The same guard provisiond applies to a uid before it becomes a path
# component (zylch/provisiond/handler.py _UID_RE), plus an explicit refusal
# of `.` and `..`.
check_uid() {
  local u="$1"
  [[ "$u" =~ ^[A-Za-z0-9_.-]+$ ]] || die "uid has characters outside [A-Za-z0-9_.-]"
  [ "$u" != "." ] && [ "$u" != ".." ] || die "uid may not be . or .."
}
check_group() {
  [[ "$1" =~ ^mc-c-[0-9a-f]{12}$ ]] || die "not a derived company group name: $1"
}

sha12() { printf '%s' "$1" | sha256sum | cut -c1-12; }
sha32() { printf '%s' "$1" | sha256sum | cut -c1-32; }
user_of() { echo "mc-$(sha12 "$1")"; }
group_of_key() { echo "mc-c-$(sha12 "$1")"; }

env_value() { # env_value <file> <KEY>
  local line
  line=$(grep -E "^$2=" "$1" 2>/dev/null | tail -n1 || true)
  line=${line#*=}; line=${line%\"}; line=${line#\"}
  printf '%s' "$line"
}

ensure_table() { install -m 600 -o root -g root /dev/null "$TABLE" 2>/dev/null || true; [ -f "$TABLE" ] || : > "$TABLE"; chmod 600 "$TABLE"; }
table_user() { awk -F'\t' -v u="$1" '$1==u {print $2}' "$TABLE" 2>/dev/null | tail -n1; }

verb="${1:-}"; uid="${2:-}"
case "$verb" in create|join|unjoin|delete|names) ;; *) sed -n '2,20p' "$0"; exit 2 ;; esac
[ -n "$uid" ] || die "missing <uid>"
check_uid "$uid"

profile_dir="$PROFILES/$uid"
user=$(user_of "$uid")
unit="$UNIT_PREFIX$uid.service"
dropin="$DROPIN_DIR/$unit.d/tenant.conf"
fragment="$TMPFILES_DIR/mrcalld-$user.conf"
keyfile="$KEYS_DIR/$uid"

company_group_for_profile() {
  local key
  key=$(env_value "$profile_dir/.env" MEMORY_KEY)
  [ -n "$key" ] && group_of_key "$key" || echo ""
}

case "$verb" in

names)
  echo "user:  $user"
  g=$(company_group_for_profile); echo "group: ${g:-(no MEMORY_KEY)}"
  [ -n "$g" ] && echo "store: $MEMORY/$g/$(sha32 "$(env_value "$profile_dir/.env" MEMORY_KEY)").db"
  exit 0 ;;

create)
  [ -f "$profile_dir/.env" ] || die "no profile .env at $profile_dir"
  ensure_table
  # 1. traversal on the parents (tenant users reach their profile and the
  #    store outside the unit sandbox: join-company.sh, rekey) — never list.
  chmod 0711 "$ROOT" "$ZHOME" "$PROFILES"
  install -d -m 0711 -o "$SVC_USER" -g "$SVC_USER" "$MEMORY"
  # 2. the user (no login, no home creation: HOME is the profile dir)
  if ! id "$user" >/dev/null 2>&1; then
    useradd --system --no-create-home --home-dir "$profile_dir" --shell /usr/sbin/nologin "$user"
    log "created user $user"
  fi
  # 3. company group + store directory (a sandboxed daemon cannot create them)
  group=$(company_group_for_profile)
  if [ -n "$group" ]; then
    getent group "$group" >/dev/null || { groupadd --system "$group"; log "created group $group"; }
    usermod -a -G "$group" "$user"
    install -d -m 2770 -o "$SVC_USER" -g "$group" "$MEMORY/$group"
  fi
  # 4. per-profile encryption key (root-only file read by systemd before
  #    dropping privileges). Never printed.
  install -d -m 0700 -o root -g root "$KEYS_DIR"
  if [ ! -s "$keyfile" ]; then
    ( umask 077; printf 'ENCRYPTION_KEY=%s\n' "$("$VENV/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" > "$keyfile" )
    log "minted key file for $uid"
  fi
  chmod 0400 "$keyfile"; chown root:root "$keyfile"
  # 5. per-instance drop-in: what the template cannot derive from %i
  install -d -m 0755 "$(dirname "$dropin")"
  {
    echo "# generated by mrcall-tenant create; do not edit"
    echo "[Service]"
    echo "User=$user"
    echo "Group=$user"
    [ -n "$group" ] && echo "SupplementaryGroups=$group"
    echo "BindPaths=$profile_dir"
    [ -n "$group" ] && echo "BindPaths=$MEMORY/$group"
    echo "ReadWritePaths=$profile_dir"
    [ -n "$group" ] && echo "ReadWritePaths=$MEMORY/$group"
  } > "$dropin.tmp"
  if ! cmp -s "$dropin.tmp" "$dropin" 2>/dev/null; then mv "$dropin.tmp" "$dropin"; log "wrote $dropin"; else rm -f "$dropin.tmp"; fi
  # 6. runtime socket dir: parent 0751 mrcalld:caddy (traversable by the
  #    tenant), per-uid dir 2750 <user>:caddy so the socket inherits the
  #    proxy's group and server_ws.py's chmod(0o660) lets Caddy connect.
  printf 'd %s 0751 %s %s -\nd %s/%s 2750 %s %s -\n' "$RUN_ROOT" "$SVC_USER" "$PROXY_GROUP" "$RUN_ROOT" "$uid" "$user" "$PROXY_GROUP" > "$fragment"
  systemd-tmpfiles --create "$fragment"
  # 7. profile tree: subdirs, then ownership — LAST, so any -wal/-shm a
  #    root-run rekey left behind is re-owned (plan M2.7).
  install -d -m 0750 "$profile_dir/downloads" "$profile_dir/scratch"
  chown -R "$user:$user" "$profile_dir"
  chmod 0700 "$profile_dir"; chmod 0600 "$profile_dir/.env"
  # 8. record
  grep -qP "^$uid\t" "$TABLE" || printf '%s\t%s\t%s\n' "$uid" "$user" "$(date -u +%FT%TZ)" >> "$TABLE"
  systemctl daemon-reload
  log "ready: $uid -> $user${group:+ (group $group)}"
  ;;

join)
  g="${3:-}"; [ -n "$g" ] || die "missing <company-group>"; check_group "$g"
  id "$user" >/dev/null 2>&1 || die "no user for $uid (run create first)"
  getent group "$g" >/dev/null || { groupadd --system "$g"; log "created group $g"; }
  install -d -m 2770 -o "$SVC_USER" -g "$g" "$MEMORY/$g"
  usermod -a -G "$g" "$user"
  log "$user is now in $g (keep the old group until the join finished, then unjoin)"
  ;;

unjoin)
  g="${3:-}"; [ -n "$g" ] || die "missing <company-group>"; check_group "$g"
  id "$user" >/dev/null 2>&1 || die "no user for $uid"
  gpasswd -d "$user" "$g" >/dev/null 2>&1 || true
  log "$user removed from $g"
  # the drop-in must follow the .env key: regenerate it
  "$0" create "$uid"
  ;;

delete)
  last=""; [ "${3:-}" = "--last-holder" ] && last="--last-holder"
  systemctl disable --now "$unit" >/dev/null 2>&1 || true
  if id "$user" >/dev/null 2>&1 && [ -f "$profile_dir/.env" ]; then
    # offboarding runs AS THE TENANT USER, never root, so the company
    # store's -wal/-shm keep the group ownership the other members need
    sudo -u "$user" env HOME="$profile_dir" ZYLCH_HOME="$ZHOME" MEMORY_DB_DIR="$MEMORY" \
      "$VENV/bin/zylch" -p "$uid" memory-offboard --yes $last || log "offboard reported a problem (continuing)"
  fi
  rm -rf "$profile_dir"
  rm -f "$keyfile" "$fragment"
  rm -rf "$(dirname "$dropin")" "$RUN_ROOT/$uid"
  if id "$user" >/dev/null 2>&1; then userdel "$user"; log "removed user $user"; fi
  ensure_table; grep -vP "^$uid\t" "$TABLE" > "$TABLE.tmp" || true; mv "$TABLE.tmp" "$TABLE"; chmod 600 "$TABLE"
  systemctl daemon-reload
  log "deleted $uid"
  ;;
esac
