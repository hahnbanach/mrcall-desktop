# M1 second repair: authenticate schema before using views

Evidence directory: `/home/mal/worktrees/.evidence/m10-execution-20261016/paid-budget-plan/M1/repair-r4/`.
Unqualified artifact filenames refer there. Earlier implementation/accounting
evidence and failed probes remain in the parent M1 evidence and review directory.
The unchanged product artifact has369 Python files and seven resources; its
376-file count is separate from the successor post-Stripe module inventory.

Status: M1 APPROVED by the independent reviewer; actual report retained at
`/home/mal/worktrees/.evidence/m10-execution-20261016/paid-budget-M1-review/report-r3.md`
(SHA256 `65154569cc1aab23a7d38e2dee3d53341baec6eb4e13d1a6b09af0ae38b6ec0a`). Ready
binding: `M1-ready.json`, SHA256
`d2bfdf108499e0c257e18a54e3768c756d332b941a006210966133f750518e1b`.
Both independent REVISE reports, original62-pass and prior75-pass bindings remain
unchanged. Approved brief/plan identities remain unchanged from the boundary
revision; no new framing, registry, secret or product hook was introduced.

The second independent probe correctly identified self-authentication: replacing
integrity and totals with constant-zero views disabled the schema comparison
inside integrity, despite all three reservation-insert triggers remaining intact.
Each effective INSERT guard now executes its own separate frozen-schema SELECT
before reading any accounting/integrity view. That SELECT compares the frozen
object bindings directly with main.sqlite_master; it cannot be bypassed by
replacing the integrity view that previously contained the only comparison.

The expected-binding table is itself an indirection. Its exact table definition
and immutable INSERT/UPDATE/DELETE trigger definitions are now also checked
against inline SQL literals in every effective INSERT guard. Substituting that
table with a self-reporting view, dropping its UPDATE protection and rewriting
expected view definitions, or dropping its DELETE protection and removing the
missing-object records all refuse. Frozen-schema checks execute as a separate
statement, before trusting the views or their claimed totals.

The exact two-view regression asserts all three INSERT-trigger definitions remain
byte-identical. It tries both the original extraUSD2 maximum and a zero-cost
request that budget arithmetic alone would permit. The same cases run with only
capture, admissionA or admissionB surviving. Three additional binding-indirection
poisoning/substitution cases refuse. The prior deletion, historical accounting,
numeric, concurrent, crash and installed-client cases continue to pass.

Actual full no-network execution: **86 passed, zero failures/errors/skips,
12 inherited warnings,42.92s**. `command.json` records exact clean environment,
explicit retained artifact interpreter, timestamps, exit0 and identical before/
after hashes for all six owned files. Complete stdout/JUnit and the installed
RPC/proxy/OpenRouter proof are retained beside this draft. Ruff, Ruff format,
Black26.5.1, compilation and diff checks passed; all six files stay below500lines.
The unchanged376-file product artifact parity receipt is reused as instructed;
only helper/test source changed. The separate generic-CI missing-opt-in skip
receipt remains applicable to the unchanged installed-test source. The actual
M1 acceptance execution explicitly configures its artifact and has zero skips.

Trusted maintenance still excludes removing every effective INSERT guard,
whole-store rollback, and deliberate privileged forgery/replacement of the frozen
authoritative baseline/binding evidence, which is baseline-reset/rollback
territory. This is not tamper-proof storage against the database owner. Ordinary
view/object drift and protected DML edits refuse while one effective INSERT
guard remains. The lead explicitly confirmed this existing trusted-writer limit.

This M1 proof performed no live activation, paid/funding calls or product/dependency
change. M2 controls now have separate implementation evidence and a concrete packet
in the [controls evaluation](2026-10-16-m10-paid-acceptance-controls.md). Qualified component critic/final closure is complete and published atd8df989e.
The [reviewed assembly](2026-10-16-m10-reviewed-assembly.md) additionally binds
the current376-module artifact; all actual M3 rollout acceptance remains open.
