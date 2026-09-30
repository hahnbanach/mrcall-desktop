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
#   mrcall-tenant create <uid>                 # MIGRATES a profile: user, key file, drop-in, runtime dir, subdirs, chown, company group+dir
#   mrcall-tenant join   <uid> <company-group> # add the user to a second company group (during a join)
#   mrcall-tenant unjoin <uid> <company-group> # remove it (after the join finished)
#   mrcall-tenant delete <uid>                 # stop, offboard (as the tenant user; last-holder derived), remove everything
#   mrcall-tenant unmigrate <uid>              # rollback of create: drop-in, fragment, run dir, ownership back to mrcalld, table row (keeps user + key file)
#   mrcall-tenant store  <uid>                 # 2a: company group, setgid store dir, file group/modes, mrcalld in the group
#   mrcall-tenant names  <uid>                 # print the derived names, change nothing
#   mrcall-tenant list                         # the migrated uids (tenants table)
#
# `create` is the operator's explicit migration step (runbook M2.7); the
# reconcile automation re-runs it ONLY for uids already in the table, so a
# pull never migrates a running customer by itself. Every verb is
# idempotent. Names never carry the uid or the key: user
# `mc-<sha256(uid)[:12]>`, group `mc-c-<sha256(key)[:12]>` (the same
# derivation as zylch/memory/tenant_names.py).
set -euo pipefail

SVC_USER=mrcalld
ROOT="/home/$SVC_USER"
ZHOME="$ROOT/.zylch"
PROFILES="$ZHOME/profiles"
MEMORY="$ZHOME/memory"
EMB_CACHE="$ZHOME/fastembed_cache"
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
# of `.` and `..`. A uid only ever appears inside absolute paths, after
# `-p`, or through printf '%s'; useradd/chown/gpasswd get derived names.
check_uid() {
  local u="$1"
  [[ "$u" =~ ^[A-Za-z0-9_.-]+$ ]] || die "uid has characters outside [A-Za-z0-9_.-]"
  [ "$u" != "." ] && [ "$u" != ".." ] || die "uid may not be . or .."
}
check_group() { [[ "$1" =~ ^mc-c-[0-9a-f]{12}$ ]] || die "not a derived company group name: $1"; }

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

ensure_table() { [ -f "$TABLE" ] || install -m 600 -o root -g root /dev/null "$TABLE"; chmod 600 "$TABLE"; }
table_has() { awk -F'\t' -v u="$1" '$1==u {found=1} END {exit !found}' "$TABLE" 2>/dev/null; }
table_drop() { awk -F'\t' -v u="$1" '$1!=u' "$TABLE" > "$TABLE.tmp" && mv "$TABLE.tmp" "$TABLE" && chmod 600 "$TABLE"; }

# Run the engine CLI as a tenant user, outside the unit: the data root is
# passed explicitly (nothing else sets it there) and umask 007, or a store
# or -wal/-shm created here would be 0644 and read-only for the other
# members of the company group.
as_tenant() { # as_tenant <user> <profile_dir> <zylch args...>
  local u="$1" pd="$2"; shift 2
  sudo -u "$u" env HOME="$pd" ZYLCH_HOME="$ZHOME" MEMORY_DB_DIR="$MEMORY" \
    bash -c 'umask 007; exec "$@"' _ "$VENV/bin/zylch" "$@"
}

verb="${1:-}"
case "$verb" in
  list) ensure_table; cut -f1 "$TABLE"; exit 0 ;;
  create|join|unjoin|delete|names|unmigrate|store) ;;
  *) sed -n '2,27p' "$0"; exit 2 ;;
esac
uid="${2:-}"; [ -n "$uid" ] || die "missing <uid>"
check_uid "$uid"

profile_dir="$PROFILES/$uid"
user=$(user_of "$uid")
unit="$UNIT_PREFIX$uid.service"
dropin_d="$DROPIN_DIR/$unit.d"
dropin="$dropin_d/tenant.conf"
fragment="$TMPFILES_DIR/mrcalld-$user.conf"
keyfile="$KEYS_DIR/$uid"

profile_key() { env_value "$profile_dir/.env" MEMORY_KEY; }
company_group_for_profile() { local k; k=$(profile_key); [ -n "$k" ] && group_of_key "$k" || echo ""; }

# 2a before 2b: a sandboxed daemon cannot see a legacy `<key>.db` (the
# memory dir is a tmpfs plus its bound group dir) and would start an empty
# store. Refuse to migrate or join while the legacy file still exists.
require_relocated() { # require_relocated <key>
  local k="$1" g
  [ -n "$k" ] || return 0
  g=$(group_of_key "$k")
  if [ -f "$MEMORY/$k.db" ] && [ ! -f "$MEMORY/$g/$(sha32 "$k").db" ]; then
    die "the company store still has its legacy name; run 2a first: zylch -p $uid memory-relocate-store (all of the company's daemons stopped)"
  fi
}

# The company group, its store directory and the files already in it. 2a
# moves a store created by mrcalld (`mrcalld:mrcalld`, 0640/0660) into the
# setgid dir; the directory's group does not reach files that already
# exist, so without this a tenant daemon gets EACCES on the store and its
# lock files (scratch VM probe 2026-09-30). mrcalld stays in the group
# during the transition: an unmigrated daemon of the same company must be
# able to write the -wal/-shm a tenant created (0660 <tenant>:<group>).
ensure_company_store() { # ensure_company_store <group>
  local g="$1"
  getent group "$g" >/dev/null || { groupadd --system "$g"; log "created group $g"; }
  install -d -m 0711 -o "$SVC_USER" -g "$SVC_USER" "$MEMORY"
  [ -L "$MEMORY/$g" ] && die "$MEMORY/$g is a symlink; refusing"
  install -d -m 2770 -o "$SVC_USER" -g "$g" "$MEMORY/$g"
  find "$MEMORY/$g" -maxdepth 1 -type f -exec chgrp "$g" {} + -exec chmod g+rw,o= {} +
  usermod -a -G "$g" "$SVC_USER"
}

write_dropin() { # write_dropin <group or empty>
  local group="$1"
  install -d -m 0755 "$dropin_d"
  {
    echo "# generated by mrcall-tenant create; do not edit — plan M2 per-tenant identity + sandbox"
    echo "[Service]"
    echo "User=$user"
    echo "Group=$user"
    [ -n "$group" ] && echo "SupplementaryGroups=$group"
    echo "Environment=HOME=$profile_dir"
    echo "Environment=ZYLCH_HOME=$ZHOME"
    echo "Environment=MEMORY_DB_DIR=$MEMORY"
    echo "Environment=PYTHONDONTWRITEBYTECODE=1"
    echo "WorkingDirectory=$profile_dir"
    # reset the template's shared key, then the root-only per-profile file
    # (no `-`: a missing key FAILS the unit)
    echo "EnvironmentFile="
    echo "EnvironmentFile=$keyfile"
    echo "ProtectSystem=strict"
    echo "ProtectHome=tmpfs"
    echo "BindReadOnlyPaths=$REPO"
    echo "BindReadOnlyPaths=$EMB_CACHE"
    echo "BindPaths=$profile_dir"
    [ -n "$group" ] && echo "BindPaths=$MEMORY/$group"
    echo "ReadWritePaths=$profile_dir"
    [ -n "$group" ] && echo "ReadWritePaths=$MEMORY/$group"
    echo "ReadWritePaths=$RUN_ROOT/$uid"
    echo "PrivateTmp=yes"
    echo "NoNewPrivileges=yes"
    echo "CapabilityBoundingSet="
    echo "RestrictSUIDSGID=yes"
    echo "RestrictNamespaces=yes"
    echo "LockPersonality=yes"
    echo "ProtectKernelTunables=yes"
    echo "ProtectKernelModules=yes"
    echo "ProtectControlGroups=yes"
    echo "UMask=0007"
    echo "ExecStart="
    echo "ExecStart=$VENV/bin/zylch -p $uid serve --unix $RUN_ROOT/$uid/ws.sock"
    echo "ExecStopPost="
    echo "ExecStopPost=/bin/rm -f $RUN_ROOT/$uid/ws.sock"
  } > "$dropin.tmp"
  if ! cmp -s "$dropin.tmp" "$dropin" 2>/dev/null; then mv "$dropin.tmp" "$dropin"; log "wrote $dropin"; else rm -f "$dropin.tmp"; fi
}

case "$verb" in

store)
  # 2a, after `zylch -p <uid> memory-relocate-store` with every daemon of
  # the company stopped: group, setgid dir, file group + g+rw, mrcalld in
  # the group. Migrates nobody; start the company's daemons afterwards so
  # the unmigrated ones pick up the new supplementary group.
  key=$(profile_key); [ -n "$key" ] || die "profile has no MEMORY_KEY"
  g=$(group_of_key "$key")
  [ -f "$MEMORY/$key.db" ] && die "legacy store still present; run memory-relocate-store first"
  ensure_company_store "$g"
  log "company store ready: $g"
  ;;

names)
  echo "user:  $user"
  g=$(company_group_for_profile); echo "group: ${g:-(no MEMORY_KEY)}"
  [ -n "$g" ] && echo "store: $MEMORY/$g/$(sha32 "$(profile_key)").db"
  exit 0 ;;

create)
  [ -f "$profile_dir/.env" ] || die "no profile .env at $profile_dir"
  [ -L "$profile_dir/.env" ] && die "$profile_dir/.env is a symlink; refusing"
  key=$(profile_key); require_relocated "$key"
  ensure_table
  # 1. traversal on the parents (tenant users reach their profile and the
  #    store outside the unit sandbox: join-company.sh, rekey) — never list.
  #    The profiles dir stays writable by mrcalld (provisiond writes there).
  chmod 0711 "$ROOT" "$ZHOME" "$PROFILES"
  install -d -m 0711 -o "$SVC_USER" -g "$SVC_USER" "$MEMORY"
  # 2. the embedding cache, pre-warmed as mrcalld (runbook step 0) and
  #    bound read-only. mrcalld's daemons wrote it under UMask=0007, so
  #    make it world-readable or the tenant gets EACCES on the bind.
  install -d -m 0755 -o "$SVC_USER" -g "$SVC_USER" "$EMB_CACHE"
  chmod -R u=rwX,go=rX "$EMB_CACHE"
  # 3. the user (no login, no home creation: HOME is the profile dir)
  if ! id "$user" >/dev/null 2>&1; then
    useradd --system --no-create-home --home-dir "$profile_dir" --shell /usr/sbin/nologin "$user"
    log "created user $user"
  fi
  # 4. company group + store directory (a sandboxed daemon cannot create them)
  group=""
  if [ -n "$key" ]; then
    group=$(group_of_key "$key")
    ensure_company_store "$group"
    usermod -a -G "$group" "$user"
  fi
  # 5. per-profile encryption key (root-only file read by systemd before
  #    dropping privileges). Never printed.
  install -d -m 0700 -o root -g root "$KEYS_DIR"
  if [ ! -s "$keyfile" ]; then
    ( umask 077; printf 'ENCRYPTION_KEY=%s\n' "$("$VENV/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" > "$keyfile" )
    log "minted key file for $uid"
  fi
  chmod 0400 "$keyfile"; chown root:root "$keyfile"
  # 6. per-instance drop-in: identity, key, data root, socket, sandbox
  write_dropin "$group"
  # 7. runtime socket dir: per-uid 2750 <user>:caddy so the socket inherits
  #    the proxy's group and server_ws.py's chmod(0o660) lets Caddy connect.
  #    The parent comes from tmpfiles.d/mrcalld.conf (2751 mrcalld:caddy).
  printf 'd %s/%s 2750 %s %s -\n' "$RUN_ROOT" "$uid" "$user" "$PROXY_GROUP" > "$fragment"
  systemd-tmpfiles --create "$fragment"
  # 8. profile tree: subdirs, then ownership — LAST, so any -wal/-shm a
  #    root-run rekey left behind is re-owned (plan M2.7).
  for d in downloads scratch; do
    [ -L "$profile_dir/$d" ] && die "$profile_dir/$d is a symlink; refusing"
    [ -d "$profile_dir/$d" ] || mkdir -m 0750 "$profile_dir/$d"
  done
  chown -R --no-dereference "$user:$user" "$profile_dir"
  chmod 0700 "$profile_dir"; chmod 0600 "$profile_dir/.env"
  # 9. record
  table_has "$uid" || printf '%s\t%s\t%s\n' "$uid" "$user" "$(date -u +%FT%TZ)" >> "$TABLE"
  systemctl daemon-reload
  log "ready: $uid -> $user${group:+ (group $group)}"
  ;;

join)
  g="${3:-}"; [ -n "$g" ] || die "missing <company-group>"; check_group "$g"
  id "$user" >/dev/null 2>&1 || die "no user for $uid (run create first)"
  # 2a first for the DESTINATION too: the key arrives in the environment
  # (MRCALL_JOIN_KEY, set by join-company.sh), never on argv
  if [ -n "${MRCALL_JOIN_KEY:-}" ]; then
    [ "$(group_of_key "$MRCALL_JOIN_KEY")" = "$g" ] || die "MRCALL_JOIN_KEY does not derive to $g"
    require_relocated "$MRCALL_JOIN_KEY"
  fi
  ensure_company_store "$g"
  usermod -a -G "$g" "$user"
  log "$user is now in $g (keep the old group until the join finished, then unjoin)"
  ;;

unjoin)
  g="${3:-}"; [ -n "$g" ] || die "missing <company-group>"; check_group "$g"
  id "$user" >/dev/null 2>&1 || die "no user for $uid"
  gpasswd -d "$user" "$g" >/dev/null 2>&1 || true
  log "$user removed from $g"
  # the drop-in must follow the .env key: regenerate (idempotent)
  "$0" create "$uid"
  ;;

unmigrate)
  # Rollback of `create` (runbook M2.7): the unit returns to the
  # transitional template. Keeps the user and the key file so the forward
  # path is repeatable; the caller has already run `rekey` back to the
  # shared key while the unit was stopped.
  systemctl stop "$unit" >/dev/null 2>&1 || true
  rm -rf "$dropin_d" "$RUN_ROOT/$uid"; rm -f "$fragment"
  [ -d "$profile_dir" ] && chown -R --no-dereference "$SVC_USER:$SVC_USER" "$profile_dir"
  # a -wal/-shm the tenant left on the relocated store is 0660 <tenant>:<group>;
  # give the returning mrcalld daemon the group so it can write it
  g=$(company_group_for_profile); [ -n "$g" ] && getent group "$g" >/dev/null && usermod -a -G "$g" "$SVC_USER"
  ensure_table; table_drop "$uid"
  systemctl daemon-reload
  log "unmigrated $uid (user and key file kept)"
  ;;

delete)
  [ "${3:-}" = "" ] || die "delete takes no flag: last-holder is derived from group membership"
  systemctl disable --now "$unit" >/dev/null 2>&1 || true
  group=$(company_group_for_profile)
  last=""
  if [ -n "$group" ] && getent group "$group" >/dev/null; then
    # mrcalld is in every company group during the transition; it is not a key holder
    others=$(getent group "$group" | awk -F: '{print $4}' | tr ',' '\n' | grep -v -e "^$user$" -e "^$SVC_USER$" | grep -c . || true)
    [ "$others" = 0 ] && last="--last-holder"
  fi
  if id "$user" >/dev/null 2>&1 && [ -f "$profile_dir/.env" ]; then
    # offboarding runs AS THE TENANT USER, never root, so the company
    # store's -wal/-shm keep the group ownership the other members need
    # shellcheck disable=SC2086
    as_tenant "$user" "$profile_dir" -p "$uid" memory-offboard --yes $last || log "offboard reported a problem (continuing)"
  fi
  rm -rf "$profile_dir"
  rm -f "$keyfile" "$fragment"
  rm -rf "$dropin_d" "$RUN_ROOT/$uid"
  if id "$user" >/dev/null 2>&1; then userdel "$user"; log "removed user $user"; fi
  if [ -n "$last" ] && [ -n "$group" ]; then
    rm -rf "$MEMORY/$group"; groupdel "$group" >/dev/null 2>&1 || true
    log "removed empty company group $group and its store directory"
  fi
  ensure_table; table_drop "$uid"
  systemctl daemon-reload
  log "deleted $uid"
  ;;
esac
