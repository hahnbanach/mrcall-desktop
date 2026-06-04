# Harness Backlog — Cross-cutting

Cross-cutting enforcement gaps that span engine ↔ app. Engine-only and
app-only gaps live in `engine/docs/harness-backlog.md` and (when it
materialises) `app/docs/harness-backlog.md`.

## Open

- [ ] **No contract test for the desktop ↔ mrcall-agent transport (gzip / SSE / streaming shape).**
  Discovered: 2026-05-31 (the "credits never decrease" investigation).
  Impact: the production proxy was forwarding `httpx.aiter_raw()` bytes
  with `Content-Encoding` stripped, so a gzipped SSE body landed at the
  desktop as a parseable-as-text-stream that the SSE parser silently
  dropped — `events=0 stop_reason=end_turn` with no useful error. The
  desktop also had no diagnostic for "200 OK SSE, body empty" until we
  added byte-preview + event-count logging in `proxy_client`. Same
  class of gap as the IPC contract test below, but at the HTTP
  boundary.
  Recommendation: a tiny contract test that POSTs a hello-world payload
  to `https://zylch.mrcall.ai/api/desktop/llm/proxy` and asserts the
  raw first chunk starts with `event:` (text), not `\x1f\x8b` (gzip).
  Can live in `mrcall-agent` since it's a server invariant; the
  desktop's `_wrap_gzip_iter` keeps a defensive fallback either way.

- [ ] **No CI check that the dispatcher's DEBUG `params=` log redacts new secret-bearing RPC params.**
  Discovered: 2026-05-31 (Firebase JWT leak via narration pipeline).
  Impact: stderr is captured by the renderer's narration feature and
  forwarded to the LLM proxy for summarisation. `rpc/server._redact_params`
  masks `id_token` / `access_token` / `api_key` / `password` /
  `client_secret` / `secret`, plus a per-method table. A new RPC that
  accepts (say) `otp_code` or `session_cookie` without updating the
  tables would leak silently. No test enforces "all RPCs that accept a
  bearer-like param are in the table".
  Recommendation: a pytest that walks the JSON-RPC dispatch table,
  introspects each handler's expected params via the schema / docstring,
  and asserts any field name that matches a "looks secret" heuristic
  (regex on field name only, the value is structured) is in the redact
  table.

- [ ] **No CI check that mrcall-agent's pricing YAML stays aligned with Anthropic's published prices.**
  Discovered: 2026-05-31 (Opus 4.7 priced at $15/$75, the Opus 4.1
  price; Mario was overcharged for weeks).
  Impact: `mrcall-agent/config/llm_pricing.yaml` is hand-maintained.
  Anthropic's docs page lists current pricing per model ID. A drift
  here either overcharges (user pain) or undercharges (revenue leak)
  silently. Same class of gap as the model allowlist: Haiku 4.5's
  dated ID `claude-haiku-4-5-20251001` was missing entirely until the
  desktop hit "unknown_model".
  Recommendation: a scheduled (weekly?) CI job in `mrcall-agent` that
  fetches `https://platform.claude.com/docs/en/about-claude/models/overview`,
  parses the latest comparison table, and asserts each model in the
  YAML matches the published `input` / `output` price. New models
  not in YAML → warn, don't fail (we may not be ready to bill them).
  This is a `mrcall-agent` harness gap technically, listed here for
  cross-cutting visibility.

- [ ] **faster-whisper packaging (ctranslate2 + av) unverified in a packaged build; no test for the live WhatsApp download path.**
  Discovered: 2026-05-20 (WhatsApp voice-note transcription landing —
  dev-verified only).
  Impact: the feature pulls `faster-whisper` → ctranslate2 + av (PyAV,
  bundling ffmpeg libs). `engine/zylch.spec` now ships `collect_all` hooks
  for both, but nothing yet confirms the DMG/EXE actually loads them
  at runtime — the same class of silent break that bit the Win-x64 sidecar
  (see the PyInstaller item below). Installer grows ~50–100 MB; the `small`
  model downloads at runtime (not bundled), like fastembed. Separately,
  no automated test exercises the live neonize `download_any` path
  (downloading real voice-note bytes from a connected WhatsApp).
  Recommendation: a `v*` CI smoke build that imports the engine, loads the
  faster-whisper backend, and transcribes a tiny bundled ogg in the
  packaged sidecar — folded into the per-arch installer gate (a) below so
  one job covers "installer exists AND its sidecar can transcribe".
  See [`../engine/docs/execution-plans/whatsapp-voice-transcription.md`](../engine/docs/execution-plans/whatsapp-voice-transcription.md).

- [ ] **Release workflow installs PyInstaller unpinned + the GitHub Release ships even when the Windows sidecar build fails.**
  Discovered: 2026-05-12 (after silent Win-x64 breakage across v0.1.31,
  v0.1.31-intel, and v0.1.32 went unnoticed for a week — the macOS arm64
  build kept succeeding so the GitHub Release looked fine until someone
  tried to download an EXE).
  Impact: an upstream PyInstaller release can break the Windows sidecar
  build without notice. v0.1.31..v0.1.32 hit `PyInstaller==6.20.0`
  which segfaults with `ACCESS_VIOLATION` (0xC0000005) inside the
  isolated subprocess while enumerating neonize's submodules in
  `engine/zylch.spec:13`. Same risk applies to any other unpinned
  build-time tool.
  Mitigation in place: `.github/workflows/release.yml` now pins
  `pyinstaller==6.13.0` (commit `362e1cda`).
  Outstanding harness work:
  (a) make `release.yml` FAIL the Release-attach job when any declared
      arch is missing its installer. Today the Mac job ships its DMG
      to the GitHub Release even when the Windows job exits non-zero,
      which is the load-bearing reason this regression was invisible.
      Even a "Release attached at least one installer per declared
      arch" gate would have caught it on v0.1.31 instead of v0.1.32.
  (b) consider a `requirements-build.txt` (or equivalent in the
      workflow) covering pyinstaller + electron-builder + any future
      codegen tool, with pins bumped deliberately rather than picked
      up opportunistically each run.
  (c) a scheduled smoke-build on `main` (weekly?) would catch upstream
      regressions decoupled from the tag-release cadence, so a broken
      runner isn't discovered the day Mario tries to ship.

- [ ] **No E2E test for multi-window Firebase auth flows.**
  Discovered: 2026-05-12 (during the pre-Firebase legacy-code sweep)
  Impact: two distinct identity bugs in two months — IndexedDB cross-window
  bleed (2026-05-08: legacy window inherited the proper window's
  `auth.currentUser`) and the "no identity at all" state in legacy
  windows post-rollback (2026-05-12). Both were caught only by Mario
  manually opening two BrowserWindows and visually checking the
  IdentityBanner. With per-window `inMemoryPersistence` and
  UID-keyed bindProfile, the invariant is "one window = one signin =
  one profile dir, never bleeds, never null on the signed-in side" —
  but nothing automated enforces this. A regression here is silent
  and security-relevant (wrong account seeing wrong data).
  Recommendation: a Playwright/Spectron Electron integration test
  that boots the app, signs in as user A in window 1, opens a second
  window via "Other profiles" → user B, signs in as user B, and
  asserts that each window's `IdentityBanner` shows the right
  identity AND that `profile.current()` returns the matching dir id.
  Today the closest thing we have is `npm run typecheck`, which
  catches signature drift but not semantic identity invariants.

- [ ] **No CI gate prevents committing the OAuth Client secret.**
  Discovered: 2026-05-02
  Impact: GitHub Secret Scanning catches the `GOCSPX-` prefix on push
  and triggers Google to auto-revoke within minutes. The damage is
  recoverable (re-issue the secret) but it WILL break signin in any
  in-flight build. The current defence is `app/.gitignore:15` plus the
  postinstall+CI scripts that route the value around source. A
  pre-commit hook (or repo-side server-hook) that hard-blocks any diff
  containing `GOCSPX-[A-Za-z0-9]` would catch a slip.
  Recommendation: a tiny pre-commit hook in `.git/hooks/pre-commit` or
  a `gitleaks`-style action in CI on PRs, configured to fail on any
  match against the Google client_secret regex.

- [ ] **No contract test for IPC method/payload changes.**
  Discovered: 2026-05-02
  Impact: a server-side method rename or payload shape change must be
  manually mirrored in `app/src/preload/index.ts` + `app/src/renderer/src/types.ts`.
  TypeScript catches signature mismatches inside the renderer (which is
  why `tasks.complete(task_id, note?)` was caught at typecheck this
  session) — but it does NOT catch cases where the engine and the
  preload disagree, because the preload is the only declaration of the
  surface seen by the typechecker. There is no end-to-end check that
  the JSON the renderer sends matches what the server accepts.
  Recommendation: a small Python+TS shared schema (e.g. JSON Schema
  generated from one side and consumed by the other), or at minimum a
  pytest that spins up the sidecar in-process and round-trips a
  representative payload per method.

- [ ] **No CI for `engine/make lint` and `app/npm run typecheck`.**
  Discovered: 2026-05-02
  Impact: lint/typecheck violations slip through until the next
  session's manual run. Tonight a Black-reformat issue and a TS
  arity error were both caught only because /doc-startsession ran
  the smoke check.
  Recommendation: GitHub Actions workflow that runs both on PRs.

- [ ] **No CI for `pytest` on engine.**
  Discovered: 2026-05-02
  Impact: a partial / `-k`-filtered local run hides reds. On 2026-06-04
  a filtered run reported 2 red groups while the FULL suite had 6 (3
  failed + 16 errors across 4 files); caught only by manually re-running
  the whole suite. Without CI on the full suite, a "green" claim in
  active-context.md can age into a lie.
  Recommendation: GitHub Actions step `cd engine && venv/bin/python
  -m pytest tests/workers tests/services -q`. The `tests/` directory
  as a whole is stale (separate engine harness gap), but the two
  curated dirs above are the live test set.

## Resolved

(none yet)
