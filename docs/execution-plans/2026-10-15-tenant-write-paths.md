---
status: active
---

# Tenant write paths: execution plan

<!-- doc-scope:start -->
Scope: delivery and VPS rollout of the writable-path check;
[brief](../briefs/2026-10-15-tenant-write-paths.md).
<!-- doc-scope:end -->

## M1 — Code (cloud session)

`engine/scripts/server/tenant-helper.sh`:
- the `WRITE_PATH` declaration and its checks (`read_tenant_exec`);
- `tenant.conf` grants it (`write_dropin`);
- step 6b' compares the effective `ReadWritePaths`/`BindPaths` with
  `tenant.conf`'s plus the declared directory.

Docs: `docs/remote-backend.md`. Verification: brief acceptance 1–2, run
here with real users and a stubbed `systemctl`, plus `bash -n`; one fresh
independent review.

## M2 — VPS (Remote Control session on desktop.mrcall.ai)

Order matters. With the new helper, a unit with an undeclared extra path is
refused at reconcile (exit 3). Its daemon keeps running on its previous
`tenant.conf`, but nothing is re-applied.

1. **Before pulling, read only.** For all seven units, record the effective
   `ReadWritePaths` and `BindPaths` minus `tenant.conf`'s own (paths only).
   Expected: only production has one extra directory, P. For P record:
   - owner, group and mode, and those of its entries;
   - whether any other unit's drop-ins or environment name P or a path
     inside it, support's `QONTO_HOST_ID_FILE` included (path names only,
     never contents).

   If another unit uses P, or any unit has another extra path, stop and
   report.
2. Under the reconcile lock, with production's daemon running:
   - `chown -R <production user>: P`;
   - `chmod go-w P` (and on its entries);
   - add `WRITE_PATH=P` to `/etc/mrcalld/tenant-exec/<production uid>`.

   The identity file keeps its contents.
3. Pull `main` and reconcile: exit 0, seven `ready`. Production must still
   read its Qonto host identity: check `qonto.status` or the startup log,
   as metadata only.
4. Remove `90-qonto-identity-paths.conf`, now redundant, and reconcile
   again: exit 0, seven `ready`, and production's effective
   `ReadWritePaths` unchanged.
5. Two fresh reviews, then `status: completed`.

Rollback:
- put back `90-qonto-identity-paths.conf` and the previous owner/mode
  (recorded in step 1);
- remove the `WRITE_PATH` line;
- reconcile with the previous helper (`git checkout` of the previous
  `main` in the service checkout is not allowed: revert the commit on
  `main` instead).
