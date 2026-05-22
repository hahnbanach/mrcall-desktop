---
status: implemented (dev-verified 2026-05-20); live WhatsApp download + packaged-build bundling pending
created: 2026-05-20
owner: unassigned
---

# WhatsApp voice message transcription

## Goal

Make WhatsApp voice notes (PTT / audio) readable and actionable: download
the audio, transcribe it on-device, store the text next to the message so
it shows in the Source panel and feeds memory + task extraction like any
text message.

## What was built (all 3 pieces done)

### Decisions

- **STT**: local **faster-whisper `small`, int8, CPU**. Server-side STT
  was rejected — StarChat doesn't bill OpenAI/STT credits yet, so the
  MrCall-credits route isn't available for transcription.
- **Language**: the user's language, never a hardcoded Italian default.
  `resolve_user_language()` reads the `USER_LANGUAGE` profile env → its
  ISO code if set, else `None` so faster-whisper **auto-detects**.
- **Download/transcribe decoupled**: WhatsApp media URLs expire
  server-side, so the audio bytes are downloaded at **event time** (when
  the message arrives), not lazily. Transcription is **deferred** to the
  `update` pipeline so a slow CPU pass doesn't block message ingestion.

### Architecture

1. **Download (event time)** — `whatsapp/sync.py` calls
   `client.download_media` → neonize `download_any(message)` the moment a
   `ptt`/`audio` message arrives. Bytes cached to
   `<profile>/wa_media/<msg_id>.ogg`; the row gets `media_type='voice'|'audio'`
   + `media_path` (`_extract_media_kind` classifies, fields flow through
   `_upsert_message`).
2. **Transcribe (deferred)** — `services/process_pipeline._run_memory`
   runs a faster-whisper pass over downloaded-but-untranscribed rows
   **before** memory extraction, then re-fetches so the memory worker
   sees the transcript. `whatsapp/transcription.py` holds a lazy
   faster-whisper singleton + `resolve_user_language` + `transcribe_audio`.
3. **Surface + pipeline** — transcript stored in the new `transcription`
   column. `workers/memory.py` (`_format_whatsapp_data`,
   `process_whatsapp_message`) uses `transcription or text`; the `len<20`
   skip gate is **bypassed for transcribed voice notes** (a deliberate
   voice note is signal even when short) while plain short text is still
   skipped. UI renders the transcript with a 🎤 marker + a "vocale
   trascritta" hint; `[vocale]` shown while not yet transcribed.

### Files changed

- **Engine**: NEW `whatsapp/transcription.py`; `storage/models.py`
  (+`transcription`, +`media_path` on WhatsAppMessage); `storage/database.py`
  (column migration); `storage/storage.py` (`get_untranscribed_voice_messages`,
  `set_whatsapp_transcription`, extended `get_unprocessed_whatsapp_messages`);
  `whatsapp/client.py` (`download_media`); `whatsapp/sync.py` (event-time
  download, `_extract_media_kind`, media fields); `rpc/whatsapp_actions.py`
  (wire `sync_svc.wa_client`, `transcription` in `whatsapp.list_messages`
  payload); `services/process_pipeline.py` (transcription pass + wire client
  into CLI sync); `pyproject.toml` (`faster-whisper>=1.0`).
- **App**: `types.ts` (+`transcription`), `ThreadPanel.tsx`, `views/WhatsApp.tsx`.
- **Packaging**: `engine/zylch.spec` ships PyInstaller native-lib hooks
  (`collect_all` for faster_whisper / ctranslate2 / av); the packaged-build
  smoke is still pending (see "Pending live gates").

## Test evidence (dev-verified 2026-05-20)

97 green, including: real on-device STT (auto-detect → `it`, transcript
contains "preventivo"; and forced `it`), schema migration, storage
round-trip, and the voice-gate (short *transcribed voice* NOT dropped vs
short *plain text* skipped). New tests: `tests/whatsapp/test_transcription.py`,
`tests/workers/test_voice_memory.py`. Plus an end-to-end run: real
ogg/opus → exact pipeline loop → transcript stored → memory sees real text.

## Resolved open question

neonize 0.3.17 **does** expose media download —
`download_any(message, path=None) -> Optional[bytes]` (the original plan's
open question is closed). PyAV (`av`) bundles ffmpeg libraries, so no
separate ffmpeg binary is needed (the plan's "needs ffmpeg" worry was
overstated). The plan also missed the media-expiry constraint that forces
download at event time.

## Pending live gates (NOT verified — needs Mario's phone / CI)

- **Live neonize `download_any` path** — downloading real voice-note bytes
  from a connected WhatsApp. Written defensively against the confirmed
  signature; not exercised end-to-end against a live session.
- **Packaged-build bundling** of ctranslate2 + av via PyInstaller.
  Installer grows ~50–100 MB; the model itself downloads at runtime (like
  fastembed today), not bundled. Needs a `v*` CI smoke build to confirm.

## STT options (reference — decision above)

| Approach | Pro | Con |
|---|---|---|
| **Whisper local** (faster-whisper, chosen) | local-first, no audio leaves device, no API key | downloads a model, uses CPU |
| Whisper API (OpenAI) | trivial, fast | audio leaves device, needs a key; STT not billable via MrCall credits yet |

Model sizes (downloaded once, not in the installer): faster-whisper int8
— tiny ~40 MB, base ~75 MB, **small ~250 MB (chosen)**, medium ~770 MB,
large-v3 ~1.5 GB. tiny/base are weak on non-English; `small` is the
weight/quality/speed sweet spot for Italian voice notes (bump to `medium`
if needed).
