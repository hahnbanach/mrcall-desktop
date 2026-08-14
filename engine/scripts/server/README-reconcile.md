# zylch-reconcile — automated daemon-set reconciliation

Automates what an operator used to run by hand over SSH: `sudo
update-daemons.sh` (see that script's own header for what it does and its
flags — it is unmodified by this automation). Three units:

- **zylch-reconcile.service** — oneshot. Runs `reconcile-notify.sh`, which
  flock-guards + settle-sleeps + runs `update-daemons.sh` with no flags,
  logs the full run to the journal, and optionally emails a summary. Runs
  as root (update-daemons.sh requires it).
- **zylch-reconcile.path** — triggers the service when a new entry appears
  under `/home/mrcalld/.zylch/profiles` (a new profile). Does not see
  writes deep inside an already-existing profile dir — see the comment in
  the unit file for why that is acceptable given the timer below.
- **zylch-reconcile.timer** — daily fallback (`OnCalendar=daily`,
  `Persistent=true`) so anything the path watch misses is caught within 24h.

## Install

`reconcile-notify.sh` ships inside the mrcalld checkout at its final path
already, same as update-daemons.sh — it is never copied anywhere; just
confirm it stayed executable (`chmod +x`, git preserves the bit once
committed). Only the unit files need to go to `/etc/systemd/system/`:

    sudo cp engine/scripts/systemd/zylch-reconcile.{service,path,timer} /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now zylch-reconcile.path zylch-reconcile.timer

## Optional: ops email

Set `OPS_MAIL=ops@example.com` in `/etc/mrcalld/env` (mode 600 — the same
file `zylch-server@.service` reads for `ENCRYPTION_KEY`) to get a summary
email per run, if a mailer (`mail`/`sendmail`/`msmtp`) is installed. Unset
by default: journal-only until an operator opts in.

## Watch / disable

    journalctl -t zylch-reconcile -f
    sudo systemctl disable --now zylch-reconcile.path zylch-reconcile.timer
