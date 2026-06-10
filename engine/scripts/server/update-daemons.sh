#!/usr/bin/env bash
# update-daemons.sh — idempotent updater for the mrcall-desktop WS backend.
#
# Runs as root (sudo). Pulls the engine, reinstalls deps ONLY if pyproject
# changed, ensures the systemd template + tmpfiles are current, then ensures
# exactly one daemon per discovered profile. Caddy is STATIC (per-uid
# path_regexp -> unix socket) — this script NEVER touches Caddy.
#
# Usage:
#   sudo update-daemons.sh [--dry-run] [--prune] [--restart-all]
#     --dry-run      print every mutating action, change nothing.
#     --prune        disable + stop daemons whose profile dir is gone (orphans).
#                    OFF by default ON PURPOSE: a prune run BEFORE the
#                    mal -> mrcalld cutover (Phase 4) would see the live `mal`
#                    daemon `zylch-server@Gn9Icu...` as an orphan (its profile
#                    lives under ~mal, not ~mrcalld) and STOP production. Only
#                    pass --prune once every profile lives under mrcalld.
#     --restart-all  restart every daemon even with no new commits. Default:
#                    restart only when `git pull` brought new commits, so a
#                    no-op run does not drop live WebSocket connections.
#
# Pre-cutover, run with --dry-run only. See
# docs/execution-plans/multi-profile-routing.md.
set -euo pipefail

SVC_USER=mrcalld
REPO="/home/$SVC_USER/mrcall-desktop"
ENGINE="$REPO/engine"
VENV="$ENGINE/venv"
PROFILES="/home/$SVC_USER/.zylch/profiles"
UNIT_PREFIX="zylch-server@"
UNIT_SRC="$ENGINE/scripts/systemd/zylch-server@.service"
TMPFILES_SRC="$ENGINE/scripts/tmpfiles.d/mrcalld.conf"
TMPFILES_DST="/etc/tmpfiles.d/mrcalld.conf"
LOGROTATE_SRC="$ENGINE/scripts/logrotate.d/mrcalld"
LOGROTATE_DST="/etc/logrotate.d/mrcalld"

DRY=0; PRUNE=0; RESTART_ALL=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --prune) PRUNE=1 ;;
    --restart-all) RESTART_ALL=1 ;;
    *) echo "unknown arg: $a" >&2; exit 2 ;;
  esac
done
run() { if [ "$DRY" = 1 ]; then echo "  [dry-run] $*"; else "$@"; fi; }

[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
[ -d "$REPO/.git" ] || { echo "no engine checkout at $REPO"; exit 1; }

echo "== 1. git pull =="
OLD=$(sudo -u "$SVC_USER" git -C "$REPO" rev-parse HEAD)
run sudo -u "$SVC_USER" git -C "$REPO" pull --ff-only
NEW=$(sudo -u "$SVC_USER" git -C "$REPO" rev-parse HEAD)
echo "  HEAD: $OLD -> $NEW"
CODE_CHANGED=0; [ "$OLD" != "$NEW" ] && CODE_CHANGED=1

echo "== 2. reinstall deps only if pyproject changed =="
if [ "$CODE_CHANGED" = 1 ] && ! sudo -u "$SVC_USER" git -C "$REPO" diff --quiet "$OLD" "$NEW" -- engine/pyproject.toml; then
  echo "  engine/pyproject.toml changed -> pip install -e ."
  run sudo -u "$SVC_USER" "$VENV/bin/pip" install -e "$ENGINE" -q
else
  echo "  engine/pyproject.toml unchanged -> editable install already current"
fi

echo "== 2b. ensure systemd template + tmpfiles are current =="
run install -m 644 "$UNIT_SRC" "/etc/systemd/system/zylch-server@.service"
run install -m 644 "$TMPFILES_SRC" "$TMPFILES_DST"
run install -m 644 "$LOGROTATE_SRC" "$LOGROTATE_DST"
run systemd-tmpfiles --create "$TMPFILES_DST"
run systemctl daemon-reload

echo "== 3. discover profiles (dir with .env that sets OWNER_ID) =="
UIDS=()
if [ -d "$PROFILES" ]; then
  for d in "$PROFILES"/*/; do
    [ -f "${d}.env" ] || continue
    grep -qE '^OWNER_ID=.+' "${d}.env" || continue
    UIDS+=("$(basename "$d")")
  done
fi
echo "  found ${#UIDS[@]}: ${UIDS[*]:-<none>}"

echo "== 3b. one daemon per profile (enable + start/restart) =="
for u in "${UIDS[@]:-}"; do
  [ -n "$u" ] || continue
  run systemctl enable "$UNIT_PREFIX$u" >/dev/null 2>&1 || true
  if ! systemctl is-active --quiet "$UNIT_PREFIX$u"; then
    echo "  $u: not active -> start"
    run systemctl start "$UNIT_PREFIX$u"
  elif [ "$RESTART_ALL" = 1 ] || [ "$CODE_CHANGED" = 1 ]; then
    echo "  $u: active -> restart"
    run systemctl restart "$UNIT_PREFIX$u"
  else
    echo "  $u: active + no change -> leave (keep live WS connections)"
  fi
done

echo "== 4. orphans (loaded instances without a profile dir) =="
mapfile -t INSTANCES < <(systemctl list-units --all --no-legend --plain "${UNIT_PREFIX}*" 2>/dev/null | awk '{print $1}')
for name in "${INSTANCES[@]:-}"; do
  [ -n "$name" ] || continue
  inst="${name#"$UNIT_PREFIX"}"; inst="${inst%.service}"
  [ -n "$inst" ] || continue
  found=0; for u in "${UIDS[@]:-}"; do [ "$u" = "$inst" ] && found=1; done
  [ "$found" = 1 ] && continue
  if [ "$PRUNE" = 1 ]; then
    echo "  ORPHAN $inst -> disable --now"
    run systemctl disable --now "$UNIT_PREFIX$inst"
  else
    echo "  ORPHAN $inst -> skipped (pass --prune to disable; NEVER before cutover)"
  fi
done

echo "done. (${#UIDS[@]} profiles; code_changed=$CODE_CHANGED dry_run=$DRY prune=$PRUNE)"
