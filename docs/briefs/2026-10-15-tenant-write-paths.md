# Tenant write paths: the helper checks what a hosted daemon can write

<!-- doc-scope:start -->
Scope: why and how `mrcall-tenant create` bounds a migrated unit's writable
and bound paths. The plan is [here](../execution-plans/2026-10-15-tenant-write-paths.md).
<!-- doc-scope:end -->

## Intent

After the [sandbox rollout](../execution-plans/2026-09-29-toward-sandbox.md)
`create` verified a unit's command, user, `ProtectHome` and environment
files, but not its writable paths. A root-written operator drop-in could add
`ReadWritePaths`/`BindPaths` and widen a tenant's sandbox with no check.
Production already has one: its Qonto host identity directory
(`QONTO_HOST_ID_FILE`, `engine/zylch/qonto/identity.py:host_identity`) is
writable through `90-qonto-identity-paths.conf`. If that directory were
shared with another tenant it would be a write channel between them.

## Scope

- `create` refuses any effective `ReadWritePaths`/`BindPaths` beyond
  `tenant.conf`'s own plus one declared directory.
- The declaration `/etc/mrcalld/tenant-exec/<uid>` gains `WRITE_PATH=<dir>`
  (at most once). `tenant.conf` grants it.
- A declared directory must be owned by the tenant's user, carry no
  group/other write bit, and lie outside the profiles, memory, `/run`, the
  checkout, the releases, `/etc`, `/usr`, `/root` and kernel trees.
- Out of scope: what Qonto needs the identity for (the Qonto workstream's
  decision), and the other items left open by the sandbox plan.

## Acceptance

1. Helper tests with real users: a declared tenant-owned `0700` directory
   passes; a group-writable, root-owned or system-tree one, a duplicate key
   and an unknown key are refused.
2. The effective-path check passes `tenant.conf` plus the declared
   directory (with `-` prefixes and duplicates), and refuses an extra
   writable path and an extra or moved bind.
3. VPS: production's directory is the tenant's alone, declared, with all
   seven units `ready` at reconcile exit 0. The redundant operator drop-in
   is then removed with the effective paths unchanged.

## Assumptions

- Production is the only unit with an extra writable path. The VPS
  inventory in the plan's first step verifies this before the code reaches
  the host.
- No unit needs a second extra directory.
