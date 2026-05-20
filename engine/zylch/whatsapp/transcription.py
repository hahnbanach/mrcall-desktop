"""On-device speech-to-text for WhatsApp voice notes (faster-whisper).

The model is loaded lazily on first use (downloaded to the Hugging Face
cache like fastembed's ONNX model — not bundled in the installer) and
held as a process-wide singleton behind a lock. Transcription runs on
CPU with int8 quantisation: small footprint (~250MB), a one-off
multi-second first-load, then a few seconds per voice note.

Decoupling note: callers download the audio bytes at WhatsApp event
time (URLs expire server-side) but invoke :func:`transcribe_audio` later
in batch from the update pipeline, where the CPU cost is acceptable.

Graceful degradation: every failure path (missing dependency, model
load error, decode error, empty output) returns ``None`` and logs —
never raises — so sync and the update pipeline are never broken by STT.
"""

import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# faster-whisper model size. "small" int8/cpu auto-detected Italian
# (prob 1.00) and transcribed a real WhatsApp-shaped ogg/opus perfectly
# in ~2-4s after a ~8s first load. Larger sizes raise latency without a
# meaningful quality gain for short voice notes.
_MODEL_SIZE = "small"

# Two-letter ISO codes the desktop exposes as USER_LANGUAGE. Kept in
# sync with services.solve_constants._LANGUAGE_NAMES — the canonical set
# the rest of the engine validates against. We pass these straight to
# faster-whisper, which accepts ISO 639-1 codes.
_SUPPORTED_LANGUAGES = ("it", "en", "es", "fr", "de", "pt", "nl")

_model = None
_model_lock = threading.Lock()


def _get_model():
    """Return the lazily-loaded faster-whisper model singleton.

    Returns:
        A ``faster_whisper.WhisperModel`` instance.

    Raises:
        ImportError: faster-whisper (or a native dep) is not installed.
        Exception: model construction failed (e.g. download error).
    """
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            # Lazy import: keep the faster-whisper / ctranslate2 import
            # cost (and any native-lib load) off every non-STT code path.
            from faster_whisper import WhisperModel

            logger.info(f"[stt] loading faster-whisper model={_MODEL_SIZE} (int8/cpu)…")
            _model = WhisperModel(_MODEL_SIZE, device="cpu", compute_type="int8")
            logger.info(f"[stt] model loaded model={_MODEL_SIZE}")
    return _model


def resolve_user_language() -> Optional[str]:
    """Resolve the user's configured language to a faster-whisper ISO code.

    Reads ``USER_LANGUAGE`` from the process env — the same field
    :func:`zylch.services.solve_constants.get_user_language_directive`
    consumes. Never invents a default: an unset/empty/unrecognised value
    yields ``None`` so the caller lets faster-whisper auto-detect rather
    than forcing Italian (or any other language) onto the audio.

    Returns:
        The two-letter ISO code (e.g. ``"it"``) when configured and
        recognised, otherwise ``None`` (auto-detect).
    """
    lang = (os.environ.get("USER_LANGUAGE", "") or "").strip().lower()
    resolved = lang if lang in _SUPPORTED_LANGUAGES else None
    logger.debug(f"[stt] resolve_user_language(USER_LANGUAGE={lang!r}) -> {resolved!r}")
    return resolved


def transcribe_audio(path: str, language: Optional[str] = None) -> Optional[str]:
    """Transcribe an audio file to text on-device.

    Args:
        path: Absolute path to the audio file (ogg/opus, mono 16kHz for
            WhatsApp voice notes — PyAV's bundled ffmpeg handles decode).
        language: Two-letter ISO code to force, or ``None`` to
            auto-detect. Callers pass :func:`resolve_user_language`'s
            result; ``None`` MUST NOT be silently coerced to Italian.

    Returns:
        The full transcript (no truncation), or ``None`` on any failure
        (missing dependency, model-load error, decode error, empty
        result).
    """
    try:
        model = _get_model()
    except ImportError:
        logger.warning(f"[stt] faster-whisper not installed — skipping transcription of {path}")
        return None
    except Exception as e:
        logger.error(f"[stt] model load failed: {e}")
        return None

    try:
        segments, info = model.transcribe(path, language=language or None)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        logger.info(
            f"[stt] transcribe_audio(path={path}, language={language!r}) -> "
            f"lang={info.language} prob={info.language_probability:.2f} "
            f"chars={len(text)}"
        )
        return text or None
    except Exception as e:
        logger.error(f"[stt] transcription failed for path={path}: {e}")
        return None
