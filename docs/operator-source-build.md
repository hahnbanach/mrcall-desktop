# Current-main operator MCP source

The candidate packages the current-main engine and an explicitly reviewed kernel
MCP helper slice. Desktop remains the configurator. This build does not establish
standalone dependency installation, GUI behavior, provider acceptance, full kernel
CLI compatibility or adoption of kernel exact-send/publication capabilities.

The Desktop manifest enumerates every engine package/test hash, four required
native guard hashes and the complete paired kernel Git package/resource/metadata
identity. The paired kernel commit is
`67bf9ddc9c9549cf8287df0307f3c6e092e22e20`; its 136 `cs/` paths and
`pyproject.toml` are read exclusively from that Git commit. Absolute historical
origins in provenance are never build inputs. No kernel working-tree manifest is
required or read.

Run the builder with Python `-I -S -B`, `--kernel-root`, the exact
`--kernel-ref`, `--output`, `--python` and repeated `--dependency-site` directories.
The default `--desktop-root` is the script's repository. The default Desktop
`--source-mode working-tree` exports only explicit manifest inputs plus versioned
test support and build metadata. For final reconstruction use `--source-mode git`
with `--desktop-ref` naming the actual reviewed source commit. Kernel exports
always use Git, including development builds. A missing or mismatched pairing
fails before the build. Kernel pairing approval remains limited to the manifest's
explicit compatibility scope.

The builder invokes existing `setuptools.build_meta.build_wheel` directly, without
pip, dependency installation or network. Its default `SOURCE_DATE_EPOCH` is
`1704067200`. It retains clean `source-export-*` trees, per-package build logs,
wheels and `build-report.json` with source commits, dirty-state disclosure,
manifest/input digests, build commands, exit codes and wheel hashes.

The host engine extra is `operator-mcp`: `mcp==1.30.0`,
`uvicorn>=0.54,<0.55`, and `jsonschema>=4.23,<5`. Engine version remains
`0.1.57.dev1`. Actual engine resource globs cover only `migrations/*.sql` and
`prompts/*.txt`. Existing third-party dependency directories are reused explicitly;
this is not a clean dependency environment or standalone kernel dependency claim.

Run `scripts/check_operator_source.py --report BUILD/build-report.json --output
CHECK`. Default `--tests none` physically extracts both wheels, verifies complete
package path/hash/resource sets and required native guard presence, imports CLI/MCP
entry points without starting applications, and audits every loaded `cs`/`zylch`
module against the extracted pair. A separate fresh child deliberately blocks the
MCP SDK while importing ordinary engine core/RPC/WebSocket modules. HTTP/SQLite
fixtures use temporary data and loopback-only network admission.

`--tests desktop`, `--tests kernel` or `--tests all` runs only the manifest's
selected test files. Desktop protocol classes use unittest without duplicate
imported fixture classes. Function-based native integration modules use pytest.
Kernel tests cover the selected MCP helper slice, not the wider P5 core suite.
Actual results, skips and source origins remain in check output and JSON receipts.
The standalone native executable case remains a separate acceptance boundary.

Use repeated `--test-module MODULE_STEM` to rerun only affected manifest modules.
Function-based package tests use explicit fixture imports and `--noconftest`;
the retired parent Supabase cleanup fixture is outside this isolated package
contract. Actual native integration fixtures still construct signed identities,
company enrollment and separate company/private SQLite databases.

## Retained verification

The reviewed native base is Desktop `955138f7376753d4002c457de7302360dc944ac1`.
M1 and M2 source integration are independently APPROVED. The paired kernel source
commit is published as an ancestor of kernel main
`f8085ba181429185d3c4f1f9eaf0f308a151d156`; this recipe deliberately exports
`67bf9ddc9c9549cf8287df0307f3c6e092e22e20`. Broader kernel publication does not
add its exact-publication, sent-mirror recovery or interactive exact-send engine
capabilities to this Desktop slice.

Repeated local builds produce identical wheels:

- Engine `0.1.57.dev1`: `3bdb23d054c8f46d28bf085e828621102b5624cf165a2fe6612a2f8946369e65`.
- Kernel `0.53.0`: `378e3b77d2db561a3f290bc53c902560d96661a43ccf5c7ca35ff0cc993e5c8d`.

The extracted pair has 373 engine and 136 kernel package paths and 242 audited
namespace modules. All four native contextual guard hashes match the selected
main base. Ordinary core/RPC/WebSocket imports pass with MCP unavailable.

The composed checks retain 171 protocol tests (two skips), 63 function-based engine
cases and 32 kernel helper tests (one skip). The initial 21 pytest setup errors come
from an obsolete parent Supabase fixture; explicit scoped fixture loading repairs
that harness and the affected 10 memory/11 project cases pass. Other passed cases
are not repeated. The actual SDK/native guarded flow uses signed assignment and
closure, later inbound, draft/recovery/idempotence, payload conflict and revocation.
A final combined run of the three guarded/SDK modules from the actual Git export
passes 42 cases under the repaired loader; its 274 module origin audit is retained at
`m3/committed-guarded-collection/check-report.json`. Unchanged protocol, memory/
project and kernel checks retain their earlier exact-byte evidence. Controlled
model, authority-provider and mailbox protocol fixtures establish source contracts;
they do not establish new native-client or live provider acceptance.

Source/build/check evidence is under the integration plan's evidence root:
`m1-review.md`, `m2-review.md`, `m3/handoff.json`,
`m3/final-build/build-report.json` and `m3/final-check/check-report.json`.
M3 packaging review is APPROVED. Actual Desktop source commit
`9ecd8aae418f71ea93b18695f9763858a6e10de4` and the fixed kernel commit rebuild
with the same wheel hashes; `m3/committed-build/build-report.json` and
`m3/committed-check/check-report.json` retain the actual Git-ref result. Separate
final source review and publication are governed by the completion record.

## Native management and authority

The engine registers `operator.rules.list`, `operator.rules.decide`,
`operator.rules.import_preview`, `operator.rules.import_confirm`,
`operator.operations.list` and `operator.operations.recover`. These native calls
require the authenticated verified-owner request context; imported mail and a
delegated MCP bearer cannot manufacture it. Kernel scheduled wrappers retain
all six spellings of the protected decision/import denials. Ordinary opted-in
chat rule writes use delegated revisioned authority directly; they require no
per-rule Desktop confirmation. Desktop configures accounts, services and access.
A source registration does not certify a new configurator GUI build.

A prepared reply retains native source, recipient, enrollment, assignment and
claim controls. Its draft and saved receipt share the private writer transaction;
published instruction revisions are read while the matching native company writer
guard is held. Recovery returns saved results without another generation. No MCP
sending tool or new sending authority is part of this slice. Source-free ordinary
work retains its native budget and admission behavior.

## Remaining product boundaries

The [integration plan](execution-plans/2026-11-06-operator-mcp-main-integration.md)
owns source verification and publication. New Desktop installers/configurator UI,
command-free native bootstrap, broad RPC parity, customer reply quality and
provider/FULL acceptance retain their parent gates. The existing installed
operator and dated real-client evidence remain separate from this source package.
