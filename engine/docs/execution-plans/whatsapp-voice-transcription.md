---
status: planned
created: 2026-05-20
owner: unassigned
---

# WhatsApp voice message transcription

## Goal

Make WhatsApp voice notes (PTT / audio) readable and actionable: download
the audio, transcribe it on-device, store the text next to the message so
it shows in the Source panel and feeds memory + task extraction like any
text message.

## Current state — zero

- `whatsapp/sync.py:_store_message_from_event` stores only
  `text = _extract_text(message)`. For a voice note that is empty, so the
  row lands with empty `text` and renders as `[no text]` / `[media_type]`
  in `ThreadPanel.tsx`.
- The audio blob (ogg/opus) is **never downloaded**.
- No STT anywhere. The only transcriptions in the system are MrCall
  **phone-call** transcripts, generated server-side by StarChat —
  unrelated to WhatsApp.

## What's needed (3 pieces)

1. **Download the audio** — neonize/whatsmeow can download media blobs,
   but the sync path currently keeps only the text. Add a download step
   for `ptt` / `audio` messages. **Open question:** confirm the Python
   neonize binding actually exposes media download (whatsmeow does; the
   wrapper may not).
2. **Transcribe (STT)** — see options below.
3. **Store + surface + pipeline** — save the transcription (in `text`, or
   a dedicated `transcription` column), show it in `ThreadPanel`, and let
   it enter memory/task extraction so voice notes become actionable.

## STT options

| Approach | Pro | Con |
|---|---|---|
| **Whisper local** (faster-whisper / whisper.cpp, ONNX like fastembed) | local-first, no audio leaves the device, no API key | downloads a model, uses CPU |
| Whisper API (OpenAI, ~$0.006/min) | trivial, fast | audio leaves the device, needs a key (current BYOK is chat-LLM only, not STT) |

### Model sizes (downloaded once, like fastembed — not in the installer)

| Model | PyTorch orig. | faster-whisper int8 | whisper.cpp q5 | IT quality |
|---|---|---|---|---|
| tiny | ~75 MB | ~40 MB | ~32 MB | poor |
| base | ~145 MB | ~75 MB | ~60 MB | poor |
| **small** | ~470 MB | **~250 MB** | ~190 MB | acceptable |
| **medium** | ~1.5 GB | **~770 MB** | ~540 MB | good |
| large-v3 | ~3 GB | ~1.5 GB | ~1.1 GB | excellent |

tiny/base are weak on non-English; for Italian start at `small`.

## Recommendation

**faster-whisper `small` int8 (~250 MB)** as the default — best
weight/quality/speed trade-off on CPU for Italian voice notes; bump to
`medium` (~770 MB) if `small` isn't good enough. Stays local-first: no
audio leaves the device. The model downloads on first voice note (like
fastembed today), so the installer doesn't grow — only the cache does.

## Caveats / footprint beyond the model

- **Runtime deps**: faster-whisper pulls CTranslate2 (~30–60 MB lib) +
  ffmpeg to decode ogg/opus. whisper.cpp is leaner as a dependency but
  must be built/bundled per arch.
- This is its own workstream, not a small tweak (media download + STT
  integration + storage/UI/pipeline).
