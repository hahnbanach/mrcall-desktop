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
#   mrcall-tenant unstore <uid>                # rollback of 2a (company stopped, none migrated)
#   mrcall-tenant orphans [--archive]          # stores no profile holds any more (listed by hash; archived root-only)
#   mrcall-tenant names  <uid>                 # print the derived names, change nothing
#   mrcall-tenant list                         # the migrated uids (tenants table)
#   mrcall-tenant logrotate                    # regenerate /etc/logrotate.d/mrcalld (per-tenant su)
#
# A unit that needs its own interpreter or the production voice listener
# (production@) declares it in a root-owned file the operator writes,
# /etc/mrcalld/tenant-exec/<uid> (0600 root):
#   INTERPRETER=/home/mrcalld/releases/<release>/venv/bin/zylch
#   VOICE_CONFIG=/etc/mrcalld/<file>.env
# `create` validates both, copies the voice file to a 0640 root:<tenant>
# copy the sandboxed daemon can read, and writes the command line itself;
# the operator's own command drop-ins stay in place (tenant.conf sorts last
# and its effective ExecStart is verified), so `unmigrate` returns the unit
# to exactly the command it had.
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
RELEASES="$ROOT/releases"                # pinned read-only release trees (Café124)
LOGROTATE_CONF=/etc/logrotate.d/mrcalld
# written here, then renamed: logrotate reads every file in logrotate.d, and
# a leftover `.tmp` there is a "duplicate log entry" for each stanza
LOGROTATE_TMP=/etc/mrcalld/logrotate.mrcalld.tmp
REPO="$ROOT/mrcall-desktop"
VENV="$REPO/engine/venv"
KEYS_DIR=/etc/mrcalld/keys
TABLE=/etc/mrcalld/tenants.tsv          # root-only: uid <TAB> user <TAB> created-at
DROPIN_DIR=/etc/systemd/system
TMPFILES_DIR=/etc/tmpfiles.d
RUN_ROOT=/run/mrcalld
PROXY_GROUP=caddy
UNIT_PREFIX="zylch-server@"
EXEC_DIR=/etc/mrcalld/tenant-exec        # operator-declared interpreter/voice per uid

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
  # its flat link would replace provisiond's socket in /run/mrcalld
  [ "$u" != "provisiond" ] || die "uid may not be provisiond"
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

# The reconcile lock: reuse fd 9 when the caller (an operator window, or
# join-company.sh) already holds it — flock on the inherited descriptor
# succeeds at once; a second open would wait on ourselves forever.
take_lock() {
  [ "$(readlink /proc/$$/fd/9 2>/dev/null)" = "$RUN_ROOT/reconcile.lock" ] || exec 9>"$RUN_ROOT/reconcile.lock"
  flock 9
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

# /etc/logrotate.d/mrcalld, generated: the unmigrated profiles' logs as
# mrcalld (their dirs are 0770 mrcalld, and root's logrotate needs `su` for
# a group-writable parent), each migrated profile's log as its own user. A
# glob would also match the migrated logs: as mrcalld that is "Permission
# denied" every night, and a second stanza for the same file is a
# "duplicate log entry" error (scratch VM probe 2026-10-01). The text is
# fixed here, in the root-owned helper, never read from the checkout.
write_logrotate() {
  local body unm=() d u
  body='    daily
    size 50M
    rotate 7
    missingok
    notifempty
    compress
    delaycompress
    # the daemon keeps zylch.log open in append mode and never reopens it
    copytruncate'
  ensure_table
  for d in "$PROFILES"/*/; do
    u=$(basename "$d"); [[ "$u" =~ ^[A-Za-z0-9_.-]+$ ]] || continue
    [ -f "$d.env" ] || continue; table_has "$u" && continue
    unm+=("$PROFILES/$u/zylch.log")
  done
  {
    echo "# generated by mrcall-tenant (plan M2); regenerated by create/unmigrate/delete and update-daemons.sh — do not edit"
    if [ ${#unm[@]} -gt 0 ]; then
      echo "${unm[*]} {"; echo "$body"; echo "    su $SVC_USER $SVC_USER"; echo "}"
    fi
    while IFS=$'\t' read -r u _; do
      [[ "$u" =~ ^[A-Za-z0-9_.-]+$ ]] && [ -d "$PROFILES/$u" ] || continue
      echo "$PROFILES/$u/zylch.log {"; echo "$body"; echo "    su $(user_of "$u") $(user_of "$u")"; echo "}"
    done < "$TABLE"
  } > "$LOGROTATE_TMP"
  chmod 0644 "$LOGROTATE_TMP"; mv "$LOGROTATE_TMP" "$LOGROTATE_CONF"
}

verb="${1:-}"
case "$verb" in
  list) ensure_table; cut -f1 "$TABLE"; exit 0 ;;
  logrotate) write_logrotate; log "wrote $LOGROTATE_CONF"; exit 0 ;;
  orphans) ;;
  create|join|unjoin|delete|names|unmigrate|store|unstore) ;;
  *) sed -n '2,30p' "$0"; exit 2 ;;
esac
# Company stores no profile holds any more: a pre-join legacy `<key>.db`
# (its name IS a key, visible to `ls`), or a derived dir left by a join
# whose last holder was deleted. Listed by a hash of the name, never the
# key; `--archive` moves them to a root-only dir (rename, no symlink
# following) and drops the empty groups. Reconcile lock held.
if [ "$verb" = orphans ]; then
  held=(); for e in "$PROFILES"/*/.env; do [ -f "$e" ] && held+=("$(env_value "$e" MEMORY_KEY)"); done
  is_held_key() { local h; for h in "${held[@]:-}"; do [ "$h" = "$1" ] && return 0; done; return 1; }
  is_held_group() { local h; for h in "${held[@]:-}"; do [ -n "$h" ] && [ "$(group_of_key "$h")" = "$1" ] && return 0; done; return 1; }
  dest=""
  if [ "${2:-}" = "--archive" ]; then
    take_lock
    dest="/root/mrcall-orphan-stores/$(date -u +%FT%H%M%SZ)"; install -d -m 0700 -o root -g root "$dest"
  fi
  for f in "$MEMORY"/*.db; do
    [ -f "$f" ] && [ ! -L "$f" ] || continue
    n=$(basename "$f" .db); is_held_key "$n" && continue
    echo "legacy store  name-sha12=$(sha12 "$n")  $(stat -c '%s bytes, modified %y' "$f")"
    [ -n "$dest" ] && for x in "$MEMORY/$n".db*; do mv -- "$x" "$dest/"; done
  done
  for d in "$MEMORY"/mc-c-*; do
    [ -d "$d" ] && [ ! -L "$d" ] || continue
    g=$(basename "$d"); is_held_group "$g" && continue
    echo "company dir   $g  $(du -sb "$d" | cut -f1) bytes"
    if [ -n "$dest" ]; then mv -- "$d" "$dest/"; groupdel "$g" >/dev/null 2>&1 || true; fi
  done
  [ -n "$dest" ] && log "archived to $dest (root-only); delete it once the backup window has passed"
  exit 0
fi

uid="${2:-}"; [ -n "$uid" ] || die "missing <uid>"
check_uid "$uid"

profile_dir="$PROFILES/$uid"
user=$(user_of "$uid")
unit="$UNIT_PREFIX$uid.service"
dropin_d="$DROPIN_DIR/$unit.d"
dropin="$dropin_d/tenant.conf"
fragment="$TMPFILES_DIR/mrcalld-$user.conf"
keyfile="$KEYS_DIR/$uid"

exec_decl="$EXEC_DIR/$uid"
voice_copy="$EXEC_DIR/$uid.voice.env"
EXEC_BIN="$VENV/bin/zylch"; VOICE_ARG=""

# The operator's declaration for a unit that cannot run the standard
# command line (production@: a release venv and --voice-config). Every
# value is checked here: a path the sandbox cannot see, a link, a writable
# file or an environment line outside the voice allowlist is refused
# rather than run. Sets declared=1 when a declaration exists; without one
# a stale voice copy is removed. Called plainly (never in `&&`/`||`), so
# `set -e` holds inside.
declared=0
VOICE_ALLOWED='^[[:space:]]*((#.*)?|(export[[:space:]]+)?(VOICE_[A-Z0-9_]*|OPENAI_[A-Z0-9_]*|VONAGE_[A-Z0-9_]*|FIREBASE_WEB_API_KEY)[[:space:]]*=.*)$'
plain_path() { # plain_path <what> <path>: absolute, no whitespace, no systemd specifier or expansion
  [[ "$2" = /* ]] || die "$1 $2 is not absolute"
  case "$2" in *[[:space:]%\$]*) die "$1 $2 contains whitespace, % or \$ (systemd would expand it); refusing" ;; esac
}
# Every name the kernel follows to reach a shebang's interpreter must be in
# a tree the sandbox has: a venv's `python` is a link, and one that lives
# (or passes) under a /home path the sandbox hides resolves fine out here
# and is ENOENT in there — the unit then dies with 203/EXEC (scratch VM
# probe 2026-10-02). Walks the chain; under the release trees no directory
# on the way may be a link either.
sandbox_sees() { # sandbox_sees <absolute path of an executable>
  local p="$1" n=0 d t
  while :; do
    case "$p" in *[[:space:]]*|*/../*|*/./*|*/..|*/.) return 1 ;; esac
    case "$p" in
      /usr/*|/bin/*|/sbin/*|/lib/*|/lib64/*|/etc/alternatives/*) ;;
      "$RELEASES"/*|"$REPO"/*) d=$(dirname -- "$p"); [ "$(realpath -e -- "$d" 2>/dev/null)" = "$d" ] || return 1 ;;
      *) return 1 ;;
    esac
    [ -L "$p" ] || break
    t=$(readlink -- "$p"); [[ "$t" = /* ]] || t="$(dirname -- "$p")/$t"
    p=$t; n=$((n + 1)); [ "$n" -lt 16 ] || return 1
  done
  [ -f "$p" ] && [ -x "$p" ]
}
read_tenant_exec() {
  declared=0
  if [ ! -e "$exec_decl" ] && [ ! -L "$exec_decl" ]; then rm -f "$voice_copy"; return 0; fi
  [ -L "$exec_decl" ] && die "$exec_decl is a symlink; refusing"
  [ -f "$exec_decl" ] || die "$exec_decl is not a regular file"
  [ "$(stat -c '%U' "$exec_decl")" = root ] || die "$exec_decl must be owned by root"
  case "$(stat -c '%a' "$exec_decl")" in 600|400|640|644) ;; *) die "$exec_decl must not be group/other-writable (0600)";; esac
  # A declaration says something or is refused: with a misspelt key the
  # unit would migrate onto the standard command line, voice silently gone
  # (scratch VM probe 2026-10-02). Only the two keys, each at most once.
  if grep -qvE '^([[:space:]]*(#.*)?|(INTERPRETER|VOICE_CONFIG)=.+)$' "$exec_decl"; then
    die "$exec_decl has a line that is not INTERPRETER=<path>, VOICE_CONFIG=<path> or a comment"
  fi
  local interp vconf rp shebang sp k
  for k in INTERPRETER VOICE_CONFIG; do
    [ "$(grep -cE "^$k=" "$exec_decl" || true)" -le 1 ] || die "$exec_decl sets $k more than once"
  done
  interp=$(env_value "$exec_decl" INTERPRETER); vconf=$(env_value "$exec_decl" VOICE_CONFIG)
  [ -n "$interp" ] || [ -n "$vconf" ] || die "$exec_decl declares neither INTERPRETER nor VOICE_CONFIG; remove it or fill it in"
  if [ -n "$interp" ]; then
    plain_path INTERPRETER "$interp"
    rp=$(realpath -e -- "$interp" 2>/dev/null) || die "INTERPRETER $interp does not exist"
    [ "$rp" = "$interp" ] || die "INTERPRETER $interp is not the real path (it is $rp)"
    case "$rp" in "$RELEASES"/*|"$REPO"/*) ;; *) die "INTERPRETER $interp is outside $RELEASES and $REPO: the sandbox cannot see it";; esac
    [ -f "$interp" ] || die "INTERPRETER $interp is not a regular file"
    # a console script runs its shebang's python: that must be visible too
    shebang=$(head -c 512 -- "$interp" | head -n 1)
    if [[ "$shebang" == '#!'* ]]; then
      sp=${shebang#\#!}; sp=${sp#"${sp%%[![:space:]]*}"}; sp=${sp%%[[:space:]]*}
      [[ "$sp" = /* ]] || die "INTERPRETER $interp: its shebang names no absolute path"
      sandbox_sees "$sp" || die "INTERPRETER $interp runs $sp, which is missing, or reached through a link or a path outside /usr, $RELEASES and $REPO: the sandbox cannot see it"
    fi
    runuser -u "$user" -- test -x "$interp" || die "$user cannot execute $interp: chmod -R go=rX $RELEASES"
    EXEC_BIN="$interp"
  fi
  if [ -n "$vconf" ]; then
    plain_path VOICE_CONFIG "$vconf"
    [ -L "$vconf" ] && die "VOICE_CONFIG $vconf is a symlink; refusing"
    [ -f "$vconf" ] || die "VOICE_CONFIG $vconf is not a regular file"
    [ "$(stat -c '%U' "$vconf")" = root ] || die "VOICE_CONFIG $vconf must be owned by root"
    # it is also loaded as an EnvironmentFile: only voice variables, one
    # per line (no tenant identity, data root, key or import path)
    if grep -qvE "$VOICE_ALLOWED" "$vconf"; then
      die "VOICE_CONFIG $vconf has a line outside VOICE_*, OPENAI_*, VONAGE_*, FIREBASE_WEB_API_KEY (or a multi-line value); remove it"
    fi
    # 0711: the tenant reaches its own copy by name, never lists the others
    install -d -m 0711 -o root -g root "$EXEC_DIR"; chmod 0711 "$EXEC_DIR"
    install -m 0640 -o root -g "$user" "$vconf" "$voice_copy"
    runuser -u "$user" -- test -r "$voice_copy" || die "$user cannot read $voice_copy (is /etc/mrcalld o+x?)"
    VOICE_ARG=" --voice-config $voice_copy"
  else
    rm -f "$voice_copy"
  fi
  declared=1
}

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

# The company group and its setgid store directory (create, join, store).
ensure_company_store() { # ensure_company_store <group>
  local g="$1"
  getent group "$g" >/dev/null || { groupadd --system "$g"; log "created group $g"; }
  install -d -m 0711 -o "$SVC_USER" -g "$SVC_USER" "$MEMORY"
  [ -L "$MEMORY/$g" ] && die "$MEMORY/$g is a symlink; refusing"
  install -d -m 2770 -o "$SVC_USER" -g "$g" "$MEMORY/$g"
}

# A refused first migration falls back to the template: tenant.conf is
# removed again (nothing has been chown'ed yet), whatever made `create`
# stop — a refusal below, or a failing systemctl/tmpfiles under `set -e`.
# An already migrated profile keeps its drop-in (its tree is tenant-owned)
# and only the error stands.
undo_first_dropin() {
  local rc=$?
  if [ "$rc" != 0 ] && ! table_has "$uid"; then
    rm -f "$dropin" "$fragment" "$voice_copy"; rmdir "$dropin_d" 2>/dev/null || true
    # step 7's run dir and flat-name link: the template's daemon binds that name
    rm -rf "${RUN_ROOT:?}/$uid"; [ -L "$RUN_ROOT/$uid.sock" ] && rm -f "$RUN_ROOT/$uid.sock"
    systemctl daemon-reload || true
  fi
  exit "$rc"
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
    # the voice copy first: the per-profile key file is read last and wins
    [ -n "$VOICE_ARG" ] && echo "EnvironmentFile=$voice_copy"
    echo "EnvironmentFile=$keyfile"
    echo "ProtectSystem=strict"
    echo "ProtectHome=tmpfs"
    echo "BindReadOnlyPaths=$REPO"
    echo "BindReadOnlyPaths=$EMB_CACHE"
    # a pinning drop-in points PYTHONPATH here; without the bind the
    # sandbox hides it and Python silently imports the checkout instead
    echo "BindReadOnlyPaths=-$RELEASES"
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
    echo "ExecStart=$EXEC_BIN -p $uid serve --unix $RUN_ROOT/$uid/ws.sock$VOICE_ARG"
    echo "ExecStopPost="
    echo "ExecStopPost=/bin/rm -f $RUN_ROOT/$uid/ws.sock"
  } > "$dropin.tmp"
  if ! cmp -s "$dropin.tmp" "$dropin" 2>/dev/null; then mv "$dropin.tmp" "$dropin"; log "wrote $dropin"; else rm -f "$dropin.tmp"; fi
}

case "$verb" in

store)
  # 2a, after `zylch -p <uid> memory-relocate-store` with every daemon of
  # the company stopped (scratch VM probe 2026-09-30): the relocated store
  # and its lock files are still `mrcalld:mrcalld` 0640/0660 — the setgid
  # dir's group does not reach files that already exist, and a tenant
  # daemon then dies with EACCES. Give them the company group, g+rw.
  # mrcalld joins the group here, and only here: during the one-per-day
  # 2b an unmigrated daemon must write the -wal/-shm a tenant created;
  # remove it (`gpasswd -d mrcalld <group>`) once the company is migrated.
  # The normalisation runs AS mrcalld, never root: the dir is writable by
  # tenants, and a root chgrp/chmod could be raced onto a symlink.
  key=$(profile_key); [ -n "$key" ] || die "profile has no MEMORY_KEY"
  g=$(group_of_key "$key")
  [ -f "$MEMORY/$key.db" ] && die "legacy store still present; run memory-relocate-store first"
  ensure_company_store "$g"
  usermod -a -G "$g" "$SVC_USER"
  runuser -u "$SVC_USER" -- find "$MEMORY/$g" -maxdepth 1 -type f -user "$SVC_USER" -links 1 \
    -exec chgrp "$g" {} + -exec chmod g+rw,o= {} +
  log "company store ready: $g (restart the company's daemons)"
  ;;

unstore)
  # Rollback of 2a for the company of <uid>: every daemon of the company
  # stopped, none of its profiles migrated. Derived store back to the
  # legacy name, files back to mrcalld:mrcalld, mrcalld out of the group,
  # empty dir and group removed. Like `store`, it does NOT take the
  # reconcile lock: the operator holds it for the whole window (runbook).
  key=$(profile_key); [ -n "$key" ] || die "profile has no MEMORY_KEY"
  g=$(group_of_key "$key"); h=$(sha32 "$key")
  for e in "$PROFILES"/*/.env; do
    [ -f "$e" ] && [ "$(env_value "$e" MEMORY_KEY)" = "$key" ] || continue
    u=$(basename "$(dirname "$e")")
    table_has "$u" && die "profile $u of this company is migrated; unmigrate it first"
    systemctl is-active --quiet "$UNIT_PREFIX$u.service" && die "stop every daemon of the company first ($u is active)"
  done
  [ -f "$MEMORY/$key.db" ] && die "the legacy store already exists; resolve by hand"
  [ -f "$MEMORY/$g/$h.db" ] || die "no derived store for this company"
  for suf in "" -wal -shm .sweep.lock .migrate.lock .join.lock; do
    [ -e "$MEMORY/$g/$h.db$suf" ] || continue
    runuser -u "$SVC_USER" -- mv -- "$MEMORY/$g/$h.db$suf" "$MEMORY/$key.db$suf"
    # -h: never follow a link; the memory root is writable by mrcalld only
    chown -h "$SVC_USER:$SVC_USER" "$MEMORY/$key.db$suf"
    runuser -u "$SVC_USER" -- chmod 0660 "$MEMORY/$key.db$suf"
  done
  gpasswd -d "$SVC_USER" "$g" >/dev/null 2>&1 || true
  rmdir "$MEMORY/$g" 2>/dev/null && { groupdel "$g" >/dev/null 2>&1 || true; log "removed $g"; } || log "$MEMORY/$g not empty; left in place"
  log "store back to its legacy name; start the company's daemons"
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
  # 6. per-instance drop-in: identity, key, data root, socket, sandbox.
  #    Another drop-in that sets ExecStart (a pinned unit with its own
  #    command line) would win or lose against tenant.conf by file name
  #    alone: refuse. The operator removes those lines first; a unit that
  #    cannot run the standard command line is not migrated by this
  #    helper. Every drop-in systemd applies is read (the
  #    template's `zylch-server@.service.d` and /run count too), and
  #    `ExecStart =` is the same assignment to systemd.
  #    A PYTHONPATH that arrives through an EnvironmentFile is refused
  #    too: tenant.conf resets the list (the shared key must go), so a pin
  #    in a file named by the template or by an earlier drop-in would be
  #    dropped without a word, and one named later cannot be checked.
  systemctl daemon-reload
  # A declared unit (tenant-exec) keeps its operator command drop-ins:
  # tenant.conf resets ExecStart and 6b verifies what systemd will run.
  trap undo_first_dropin EXIT
  read_tenant_exec
  while IFS= read -r f; do
    [ -n "$f" ] && [ "$f" != "$dropin" ] && [ -f "$f" ] || continue
    [ "$declared" = 1 ] || case "$f" in *.d/*) if grep -qE '^[[:space:]]*ExecStart[[:space:]]*=' "$f"; then die "$f sets ExecStart; tenant.conf sets the only command line a migrated unit runs (socket $RUN_ROOT/$uid/ws.sock): remove those lines first and pin a release with Environment=PYTHONPATH=…; a unit that needs another command cannot be migrated yet"; fi ;; esac
    while IFS= read -r ef; do
      ef=${ef#-}; ef=${ef%"${ef##*[![:space:]]}"}
      # a specifier (%i) names a file this loop cannot find: refuse it
      case "$ef" in *%*) die "$f: EnvironmentFile $ef uses a specifier and cannot be checked for PYTHONPATH; pin with Environment=PYTHONPATH=… in a drop-in instead" ;; esac
      if grep -qsE '^[[:space:]]*PYTHONPATH[[:space:]]*=' "$ef"; then die "$f: EnvironmentFile $ef sets PYTHONPATH; pin with Environment=PYTHONPATH=… in a drop-in instead"; fi
    done < <(sed -nE 's/^[[:space:]]*EnvironmentFile[[:space:]]*=[[:space:]]*//p' "$f")
  done < <(systemctl show -p FragmentPath -p DropInPaths --value "$unit" | tr ' ' '\n')
  write_dropin "$group"
  # 6b. what systemd will actually run
  systemctl daemon-reload
  es=$(systemctl show -p ExecStart --value "$unit")
  [ "$(grep -o 'argv\[\]=' <<< "$es" | wc -l)" = 1 ] && [[ "$es" == *"argv[]=$EXEC_BIN -p $uid serve --unix $RUN_ROOT/$uid/ws.sock$VOICE_ARG ;"* ]] \
    || die "the unit's effective ExecStart is not tenant.conf's: something else overrides it (systemctl cat $unit)"
  # 6c. a pinned PYTHONPATH must be a real path inside the bound trees,
  #    readable by the tenant, or the daemon would silently import the
  #    checkout: the sandbox hides every other path under /home, and
  #    Python skips a missing entry. No `..` and no symbolic link on the
  #    way: `releases/../x`, a link out of the tree, and a link INTO it
  #    from a place the sandbox does not have all resolve fine out here.
  envs=$(systemctl show -p Environment --value "$unit")
  # an entry systemd prints quoted (a path with a space) is not split here
  [ "$(grep -oE '(^|[ "])PYTHONPATH=' <<< "$envs" | wc -l)" = "$(tr ' ' '\n' <<< "$envs" | grep -c '^PYTHONPATH=')" ] \
    || die "cannot read the unit's PYTHONPATH (quoted, or a path with a space)"
  pp=$(tr ' ' '\n' <<< "$envs" | sed -n 's/^PYTHONPATH=//p' | tail -n1)
  IFS=: read -ra pparts <<< "$pp"
  for p in "${pparts[@]}"; do
    [ -n "$p" ] || continue
    [[ "$p" = /* ]] || die "PYTHONPATH $p is not absolute"
    for q in "$p" "$p/zylch/__init__.py"; do
      rp=$(realpath -e -- "$q" 2>/dev/null) || die "PYTHONPATH $p: $q does not exist"
      [ "$rp" = "$q" ] || die "PYTHONPATH $p: $q is not the real path (it is $rp): no symbolic link, no \`..\`, no trailing slash"
      case "$rp" in "$REPO"/*|"$RELEASES"/*) ;; *) die "PYTHONPATH $p is $rp, outside $REPO and $RELEASES: the sandbox cannot see it";; esac
    done
    runuser -u "$user" -- test -r "$p/zylch/__init__.py" || die "$user cannot read $p/zylch/__init__.py: chmod -R go=rX $RELEASES (runbook step 0), then create again"
  done
  # 7. runtime socket dir: per-uid 2750 <user>:caddy so the socket inherits
  #    the proxy's group and server_ws.py's chmod(0o660) lets Caddy connect.
  #    The parent comes from tmpfiles.d/mrcalld.conf (2751 mrcalld:caddy).
  #    The flat name becomes a symlink to the new socket, so Caddy's one
  #    static upstream `/run/mrcalld/<uid>.sock` serves migrated and
  #    unmigrated daemons alike: no failover, no shared health state (the
  #    dual-upstream variant 503'd every uid after one missing one).
  {
    printf 'd %s/%s 2750 %s %s -\n' "$RUN_ROOT" "$uid" "$user" "$PROXY_GROUP"
    printf 'L+ %s/%s.sock - - - - %s/%s/ws.sock\n' "$RUN_ROOT" "$uid" "$RUN_ROOT" "$uid"
  } > "$fragment"
  systemd-tmpfiles --create "$fragment"
  # 8. profile tree: subdirs, then ownership — LAST, so any -wal/-shm a
  #    root-run rekey left behind is re-owned (plan M2.7).
  for d in downloads scratch; do
    [ -L "$profile_dir/$d" ] && die "$profile_dir/$d is a symlink; refusing"
    [ -d "$profile_dir/$d" ] || mkdir -m 0750 "$profile_dir/$d"
  done
  trap - EXIT
  chown -R --no-dereference "$user:$user" "$profile_dir"
  chmod 0700 "$profile_dir"; chmod 0600 "$profile_dir/.env"
  # 9. record
  table_has "$uid" || printf '%s\t%s\t%s\n' "$uid" "$user" "$(date -u +%FT%TZ)" >> "$TABLE"
  write_logrotate
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
  # tenant.conf only: the operator's own drop-ins (a pinned release's
  # PYTHONPATH) must survive, or the rolled-back unit runs the checkout
  rm -f "$dropin"; rmdir "$dropin_d" 2>/dev/null || true
  rm -rf "$RUN_ROOT/$uid"; rm -f "$fragment" "$voice_copy"
  [ -L "$RUN_ROOT/$uid.sock" ] && rm -f "$RUN_ROOT/$uid.sock"
  [ -d "$profile_dir" ] && chown -R --no-dereference "$SVC_USER:$SVC_USER" "$profile_dir"
  # a -wal/-shm the tenant left on the relocated store is 0660 <tenant>:<group>;
  # give the returning mrcalld daemon the group so it can write it
  g=$(company_group_for_profile); [ -n "$g" ] && getent group "$g" >/dev/null && usermod -a -G "$g" "$SVC_USER"
  ensure_table; table_drop "$uid"
  systemctl daemon-reload
  write_logrotate
  log "unmigrated $uid (user and key file kept)"
  ;;

delete)
  [ "${3:-}" = "" ] || die "delete takes no flag: last-holder is derived from group membership and the other profiles' keys"
  # hold the reconcile lock (as join-company.sh does) and mark the profile,
  # so no reconcile re-enables the unit while offboarding or after a
  # failed offboard (update-daemons.sh skips a profile with .deleting)
  take_lock
  [ -d "$profile_dir" ] && [ ! -L "$profile_dir" ] && install -m 0600 -o root -g root /dev/null "$profile_dir/.deleting"
  systemctl disable --now "$unit" >/dev/null 2>&1 || true
  group=$(company_group_for_profile)
  last=""
  if [ -n "$group" ] && getent group "$group" >/dev/null; then
    # mrcalld is in every company group during the transition; it is not a key holder
    others=$(getent group "$group" | awk -F: '{print $4}' | tr ',' '\n' | grep -v -e "^$user$" -e "^$SVC_USER$" | grep -c . || true)
    # an UNMIGRATED profile of the same company runs as mrcalld and is in
    # no group: count every other profile whose .env holds the same key
    # (scratch VM review 2026-09-30 — without this, deleting a migrated
    # Café124 profile mid-migration would delete the store the others use)
    k=$(profile_key); holders=0
    for e in "$PROFILES"/*/.env; do
      [ "$e" = "$profile_dir/.env" ] && continue
      [ -f "$e" ] && [ "$(env_value "$e" MEMORY_KEY)" = "$k" ] && holders=$((holders + 1))
    done
    [ "$others" = 0 ] && [ "$holders" = 0 ] && last="--last-holder"
  fi
  if id "$user" >/dev/null 2>&1 && [ -f "$profile_dir/.env" ]; then
    # offboarding runs AS THE TENANT USER, never root, so the company
    # store's -wal/-shm keep the group ownership the other members need
    # shellcheck disable=SC2086
    # a failed offboard would leave the owned rule rows behind with no
    # profile left to remove them: stop here, nothing deleted yet (the unit
    # is disabled); fix and re-run `delete`
    as_tenant "$user" "$profile_dir" -p "$uid" memory-offboard --yes $last || die "offboard failed; nothing deleted (unit disabled, .deleting keeps reconcile off it) — fix and re-run delete"
  fi
  rm -rf "$profile_dir"
  rm -f "$keyfile" "$fragment" "$voice_copy" "$exec_decl"
  rm -rf "$dropin_d" "$RUN_ROOT/$uid"
  [ -L "$RUN_ROOT/$uid.sock" ] && rm -f "$RUN_ROOT/$uid.sock"
  if id "$user" >/dev/null 2>&1; then userdel "$user"; log "removed user $user"; fi
  if [ -n "$last" ] && [ -n "$group" ]; then
    rm -rf "$MEMORY/$group"; groupdel "$group" >/dev/null 2>&1 || true
    log "removed empty company group $group and its store directory"
  fi
  ensure_table; table_drop "$uid"
  systemctl daemon-reload
  write_logrotate
  log "deleted $uid"
  ;;
esac
