#!/usr/bin/env bash
# reconcile-notify.sh — event-driven wrapper around update-daemons.sh.
#
# Invoked by zylch-reconcile.service (root), itself triggered by
# zylch-reconcile.path (new profile dir under ~mrcalld/.zylch/profiles) or
# zylch-reconcile.timer (daily fallback). Runs as root because
# update-daemons.sh itself requires root (see that script's own header).
#
# What this does, in order:
#   1. Take a non-blocking flock so a burst of overlapping triggers (e.g. an
#      rsync dropping many files into a new profile dir, each write firing
#      the .path unit) coalesces into a single run instead of stacking
#      concurrent update-daemons.sh invocations: if the lock is already
#      held, this invocation just logs and exits 0 immediately — whichever
#      run currently holds the lock is the one that reconciles.
#   2. Sleep SETTLE_SECONDS before doing anything else, so a burst that is
#      still landing (more files/dirs still being written) settles before
#      update-daemons.sh reads the profiles/ tree. Only the run that holds
#      the lock sleeps; a run that lost the flock race above never reaches
#      this line, so a burst of N triggers costs one sleep, not N.
#   3. Run update-daemons.sh with NO flags — exactly what an operator types
#      by hand today (see its own header comment). Capture combined
#      stdout+stderr and the exit code without letting `set -e` here
#      swallow a nonzero exit from that script.
#   4. Log the full run to the journal under a stable tag (zylch-reconcile),
#      regardless of whether this invocation was triggered by systemd or
#      run by hand from a terminal (systemd's own default per-unit journal
#      capture would only apply to the systemd-triggered case, and would
#      tag it by unit name, not by this fixed tag — piping through
#      systemd-cat explicitly is what keeps the tag stable either way).
#   5. If OPS_MAIL is set (sourced from /etc/mrcalld/env, the same file
#      zylch-server@.service already reads for ENCRYPTION_KEY) and a
#      mailer is available on PATH, send a short summary. Any failure here
#      is logged and swallowed — notification is best-effort, never fatal.
#   6. Exit with update-daemons.sh's own exit code. That is what the
#      .service unit reports to systemd; notification failures never
#      change it.
set -euo pipefail

TAG=zylch-reconcile
SVC_USER=mrcalld
REPO="/home/$SVC_USER/mrcall-desktop"
UPDATE_DAEMONS="$REPO/engine/scripts/server/update-daemons.sh"
LOCK_FILE=/run/mrcalld/reconcile.lock
SETTLE_SECONDS=10

log() { # log <message> [priority: info|warning|err ...] — never fatal.
  printf '%s\n' "$1" | systemd-cat -t "$TAG" -p "${2:-info}" || true
}

# Optional operator config. Systemd already loads this file for the
# .service unit via EnvironmentFile=-/etc/mrcalld/env, but we source it
# here too so this script behaves identically when run by hand (e.g. an
# operator testing it interactively via sudo, outside of systemd). The
# guard makes a missing file a non-event: OPS_MAIL stays unset and
# notification is skipped (journal-only), which is the default until an
# operator opts in.
if [ -r /etc/mrcalld/env ]; then
  # shellcheck disable=SC1091
  source /etc/mrcalld/env || true
fi

# Defensive only: /run/mrcalld is normally already created at boot by the
# tmpfiles.d entry this repo ships (engine/scripts/tmpfiles.d/mrcalld.conf,
# owner mrcalld:caddy mode 2750), and that entry is only usable once an
# operator has run update-daemons.sh at least once (it installs it) — which
# is a precondition of ever getting to the point of installing this
# automation in the first place. We run as root so we can always write a
# lock file into it either way; this just avoids a hard failure on the
# unlikely race where this fires before that dir exists.
mkdir -p /run/mrcalld

exec 200>"$LOCK_FILE"
if ! flock -n 200; then
  log "reconcile already in progress (lock held on $LOCK_FILE) — skipping this trigger; it coalesces into the in-flight run"
  exit 0
fi

log "trigger received — settling ${SETTLE_SECONDS}s before running update-daemons.sh (lets a burst of profile-dir writes land)"
sleep "$SETTLE_SECONDS"

[ -x "$UPDATE_DAEMONS" ] || { log "update-daemons.sh not found or not executable at $UPDATE_DAEMONS" err; exit 1; }

set +e
RUN_OUTPUT="$("$UPDATE_DAEMONS" 2>&1)"
EXIT_CODE=$?
set -e

# The "counts line" is update-daemons.sh's own final unconditional summary,
# e.g. "done. (3 profiles; code_changed=1 dry_run=0 prune=0)". `|| true`
# guards the grep miss case (script exited before reaching it) under
# `pipefail`, so that case falls through to the explicit fallback below
# instead of aborting this script.
COUNTS_LINE="$(printf '%s\n' "$RUN_OUTPUT" | grep -E '^done\.' | tail -n1 || true)"
[ -n "$COUNTS_LINE" ] || COUNTS_LINE="(no summary line — update-daemons.sh exited $EXIT_CODE before reaching it)"

LOG_PRIORITY=info
[ "$EXIT_CODE" = 0 ] || LOG_PRIORITY=err

{
  printf 'update-daemons.sh run: exit=%s\n' "$EXIT_CODE"
  printf '%s\n' "$RUN_OUTPUT"
} | systemd-cat -t "$TAG" -p "$LOG_PRIORITY" || true

# --- ops notification (best-effort, never affects our own exit code) ---
#
# Mailer availability at design time, on the host this script was written
# on: `mail` (/usr/bin/mail) and `sendmail` (/usr/sbin/sendmail) were
# present; `msmtp` and `mutt` were not. That is the dev host, not
# necessarily any given production host, and a present binary does not by
# itself prove a working outbound relay is configured (a bare `sendmail`
# from a mail-transport-agent package with no relay set up can accept and
# then silently queue or drop a message). So: OPS_MAIL is opt-in and unset
# by default (no mail is sent unless an operator sets it in
# /etc/mrcalld/env), and even when it is set and a mailer binary exists,
# delivery is treated as best-effort only. The journal write above always
# happens first and is the source of truth regardless of whether mail goes
# out — that is true whether or not any MTA is present on a given host.
if [ -n "${OPS_MAIL:-}" ]; then
  SUBJECT="zylch-reconcile on $(hostname): exit=${EXIT_CODE} — ${COUNTS_LINE}"
  if command -v mail >/dev/null 2>&1; then
    printf '%s\n' "$RUN_OUTPUT" | mail -s "$SUBJECT" "$OPS_MAIL" \
      || log "ops mail via 'mail' failed (non-fatal; see the journal entry above for the real run result)" warning
  elif command -v sendmail >/dev/null 2>&1; then
    printf 'Subject: %s\nTo: %s\n\n%s\n' "$SUBJECT" "$OPS_MAIL" "$RUN_OUTPUT" | sendmail "$OPS_MAIL" \
      || log "ops mail via 'sendmail' failed (non-fatal; see the journal entry above for the real run result)" warning
  elif command -v msmtp >/dev/null 2>&1; then
    printf 'Subject: %s\nTo: %s\n\n%s\n' "$SUBJECT" "$OPS_MAIL" "$RUN_OUTPUT" | msmtp "$OPS_MAIL" \
      || log "ops mail via 'msmtp' failed (non-fatal; see the journal entry above for the real run result)" warning
  else
    log "OPS_MAIL=$OPS_MAIL is set but no mailer (mail/sendmail/msmtp) is on PATH — notification skipped, journal is the source of truth" warning
  fi
fi

exit "$EXIT_CODE"
