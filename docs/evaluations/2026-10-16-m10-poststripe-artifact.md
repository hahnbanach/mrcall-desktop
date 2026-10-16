# M10 post-Stripe installed artifact and dependency preservation

Status: M2 independently APPROVED, with explicit inherited qualifications. The
immutable approved submission is `post-stripe-M2-review/approved-M2.md`, SHA256
`3913a4713b920018ffb6c5f201086136cb2502d1a85ecbd8f08f93fcca395cc0`.
The actual verdict/report is `post-stripe-M2-review/report.md` under the execution
evidence root. This local preparation grants no paid/live engine authority.

Evidence root: `/home/mal/worktrees/.evidence/m10-execution-20261016/post-stripe-M2/`.
The complete source milestone is [M1](2026-10-16-m10-poststripe-source.md); the
[plan](../execution-plans/2026-10-16-m10-poststripe-preservation.md) owns acceptance.

The private wheel `zylch-0.1.52+poststripe.20261016.1-py3-none-any.whl` has SHA-256 `11f2dd351b22b00dab76b2f5f3688659d23f2fd66fbff74ad57b692c5d64dcde`. All 376 Python modules and 7 required assets equal the approved M1 source and both installed copies. No engine source was edited for M2. Build ran from an owned private copy, outside the repository.

Two fresh Python 3.12 venv shells retain their respective original dependency bytes and versions: production 93 distributions including the replaced engine, Mario 75. No hardlinks, live-tree changes, dependency upgrades or old editable loader remain. The safe setuptools distutils .pth shim is retained. Separate append-only test/server harness packages have no runtime-file overlap. `final-dependency-byte-audit.json` proves unchanged dependency bytes against both originals after proof execution. Production loads its actual copied cs.operator_read at `3ab4969b3c3d61af473d418438edd82623cdeda9356337ef342979d9ac79e911`. Mario has no MCP, Uvicorn or cs package in its native environment.

Production's exact original interpreter and copied environment both fail pip check with the same three cs-kernel 0.51.0 requirements: firebase-admin, google-auth and jinja2. Mario's original and copy both print `No broken requirements found.` This is qualified inherited dependency evidence, never full kernel health or a green production pip check.

Installed checks run from this private evidence root with `-I -B`, no source PYTHONPATH, synthetic HOME/profile paths and network limited to AF_UNIX/loopback. Both CLI/serve help surfaces, native parity, actual schema/role readers, measured resolver validation and EmailSyncManager classifier prompt loader pass. Both cohorts pass 48 Stripe RPC discovery/refusal/encryption/HTTP cases. Production passes 26 MCP/native-read/Unix listener cases, 30 voice lifecycle/accounting cases and 2 voice listener lifecycle/refusal cases. Both pass 7 extra native Unix listener journeys using actual synthetic RS256 signatures, foreign-owner and session-expiry refusal. Both actual Anthropic SDK transports send/settle plain Haiku and metadata-shaped Sonnet requests over scripted HTTP, and both native OpenAI webhook verifiers construct. Production's 7 SDK request tests pass. Mario has 6 passes and one preserved test assertion failure that assumes its unchanged 0.105.2 SDK removed sampling keywords. The actual M10 sampling-free HTTP proof passes on that SDK.

Both native installed engines pass the six K3/GLM/Sonnet normal/lost-response FastAPI/disposable-PostgreSQL receipt cases: 12 cases total, no skips, receipt-only recovery and no duplicate inference/debit. These are scripted provider/credit effects and establish no actual funding. Reviewed server commit and each loaded source module are hash-bound in `server-source-identities.json`.

Protected snapshot inputs equal the original backup hashes. Each cohort boots cold and warm with its new installed engine, then reopens under its full frozen post-Stripe reader using the same native dependency environment. All original table/column/row projections survive; full warm/reopen snapshots are stable; managed enrollment/provenance and Qonto counts remain valid. Six boots pass. Expanded owned stores were removed only after streaming hash/size verification of their lossless gzip archives. All 704 frozen reader files were verified. No temporary .env remains in copied customer fixtures. Synthetic encrypted Stripe files remain byte-identical when read by each frozen reader and reject the wrong key. No protected live encrypted Stripe file was supplied, so live-file compatibility remains unavailable.

Initial owned harness mistakes remain under explicit r1/r2 directories: private-copy ownership, long Unix socket path, zero synthetic budget, an SDK-inappropriate httpx fixture and a metadata-shape assertion. They were corrected only in private proof tooling; product sources and dependency versions were unchanged. The actual Mario SDK signature assertion remains a qualified failure.

Totals: 179 pytest passes, 1 qualified assertion failure, 0 skips; 14 additional native Unix checks; 4 actual scripted Anthropic SDK HTTP requests; 6 copied-data boots. `summary.json` and hash manifests retain actual commands/logs/JUnit/source identities. Production pip-check qualification has fresh plan approval at SHA256
`473faafebe63737d2230d91993eb0e1e8fe57e1d9481528ad15f73b5d45ac777`; M2 review independently approved the actual equality/native proof. Documentation closure, separate final review, paid and live acceptance remain open.

## Immutable proof bindings

- Evidence index SHA256 `aa0745df76c28d7368ad94b4dc5f924b4422327d815abc7fa81a14a583bcce7e`.
- Summary SHA256 `74478916ba339194bd61957858e2a21a3475543c5f574a171db36fca57d1bdd1`.
- Bound inputs SHA256 `0abf946a5d78f97d27d542eec743519ba928b4d26663036b7655d67cfc36b03c`.
- Final dependency byte audit SHA256 `aea90666305bd19e8b735fe4979ab9e1331d15d3f1011c704884ba09eee9ea96`.

Real ordinary operations, funded-provider receipts,20 independent company answers,
protected both-clone acceptance, current deployment descriptors/backups and actual
canary/rollback remain required. No skipped/failed output is relabeled passing.

## Separate current-artifact guard integration

`post-stripe-budget-integration/summary.json` under the same execution evidence
root binds actual `-I -B` SDK/read-only multi-call RPC, proxy and OpenRouter
journeys on BOTH new native dependency environments. Each reaches exactly two
affordable ordinary read-tool calls and refuses the next LLM dispatch, settles a
synthetic full proxy receipt while leaving no orphaned second authorization, and
refuses a capped OpenRouter continuation. All loaded product modules belong to
the new wheel installations; the approved temporary helper loads by explicit path
outside the product package. Networks are denied and all SQLite fixtures private.
This extra integration proof follows the immutable M2 submission and does not
rewrite it. It establishes no live guard, real funding, maintenance lease or
customer memory-quality outcome. Its source/log/module hashes remain separately
available for final review.
