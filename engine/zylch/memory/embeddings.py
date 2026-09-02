"""Embedding generation using fastembed (ONNX backend)."""

import logging
import os
import threading
from pathlib import Path
from typing import Dict, List, Tuple, Union

import numpy as np

from .config import MemoryConfig

logger = logging.getLogger(__name__)


def _persistent_cache_dir() -> str:
    """Return a persistent directory for the fastembed model cache.

    The default fastembed cache lives under the OS temp dir, which macOS
    aggressively cleans (and any OS may evict after reboot), leading to
    `NO_SUCHFILE` errors on subsequent runs even though HF metadata
    stayed behind. Anchor the cache under `~/.zylch/` instead so it
    survives reboots and $TMPDIR cleanup.
    """
    cache = Path(os.path.expanduser("~/.zylch/fastembed_cache"))
    cache.mkdir(parents=True, exist_ok=True)
    return str(cache)


class EmbeddingEngine:
    """Generates semantic embeddings for text using fastembed.

    Uses ONNX runtime under the hood for fast CPU inference.
    Supports batch processing for efficiency.
    """

    def __init__(self, config: MemoryConfig):
        """Initialize embedding engine.

        Args:
            config: Memory configuration
        """
        self.config = config
        self.model_name = config.embedding_model
        self.dim = config.embedding_dim
        # One engine is shared process-wide (see `get_shared_engine`) and
        # its `encode` is reachable from worker threads, while the ONNX
        # session underneath makes no thread-safety promise. Serialize.
        self._encode_lock = threading.RLock()

        cache_dir = _persistent_cache_dir()
        logger.info(
            f"Loading embedding model: {self.model_name} "
            f"(fastembed/ONNX backend, cache_dir={cache_dir})"
        )

        from fastembed import TextEmbedding

        self.model = TextEmbedding(
            model_name=self.model_name,
            cache_dir=cache_dir,
        )

        # Verify dimensionality
        test_embedding = list(self.model.embed(["test"]))[0]
        actual_dim = len(test_embedding)
        logger.debug(
            f"[EmbeddingEngine] dimensionality check: " f"expected={self.dim}, actual={actual_dim}"
        )
        if actual_dim != self.dim:
            logger.warning(
                f"Model {self.model_name} produces "
                f"{actual_dim}-dim embeddings, "
                f"config expects {self.dim}. Updating config."
            )
            self.dim = actual_dim

        logger.info(f"Embedding engine ready: model={self.model_name}, " f"dim={self.dim}")

    def encode(self, text: Union[str, List[str]]) -> np.ndarray:
        """Generate embedding(s) for text.

        Args:
            text: Single text string or list of strings

        Returns:
            Embedding array: shape (dim,) for single text
            or (n, dim) for batch
        """
        if isinstance(text, str):
            logger.debug(f"[EmbeddingEngine] encode single text " f"(len={len(text)})")
            with self._encode_lock:
                embedding = list(self.model.embed([text]))[0]
            return np.array(embedding, dtype=np.float32)
        else:
            logger.debug(f"[EmbeddingEngine] encode batch " f"(n={len(text)})")
            with self._encode_lock:
                embeddings = list(
                    self.model.embed(
                        text,
                        batch_size=self.config.batch_size,
                    )
                )
            return np.array(embeddings, dtype=np.float32)

    def similarity(
        self,
        embedding1: np.ndarray,
        embedding2: np.ndarray,
    ) -> float:
        """Compute cosine similarity between two embeddings.

        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector

        Returns:
            Cosine similarity in range [-1, 1]
            (1 = identical, -1 = opposite)
        """
        dot_product = np.dot(embedding1, embedding2)
        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(embedding2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))

    def distance(
        self,
        embedding1: np.ndarray,
        embedding2: np.ndarray,
    ) -> float:
        """Compute cosine distance between two embeddings.

        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector

        Returns:
            Cosine distance in range [0, 2]
            (0 = identical, 2 = opposite)
        """
        return 1.0 - self.similarity(embedding1, embedding2)

    def serialize(self, embedding: np.ndarray) -> bytes:
        """Serialize embedding to bytes for storage.

        Args:
            embedding: Embedding vector

        Returns:
            Binary representation (numpy .tobytes())
        """
        return embedding.tobytes()

    def deserialize(self, data: bytes) -> np.ndarray:
        """Deserialize embedding from bytes.

        Args:
            data: Binary representation

        Returns:
            Embedding vector
        """
        return np.frombuffer(data, dtype=np.float32)


# ─── Process-wide engine cache ────────────────────────────────────────
#
# Building a `TextEmbedding` loads an ONNX model and runs a warm-up
# encode — seconds of work for an object that holds no per-caller state.
# Every construction site goes through `get_shared_engine` so a process
# pays that cost once per model, not once per chat turn.

_shared_engines: Dict[Tuple[str, int, int], "EmbeddingEngine"] = {}
_shared_engines_lock = threading.Lock()


def engine_cache_key(config: MemoryConfig) -> Tuple[str, int, int]:
    """Every config field that changes what an engine produces.

    The model name alone is not enough: `embedding_dim` decides the
    dimensionality check `__init__` performs, and `batch_size` decides
    how a batch encode is chunked.
    """
    return (config.embedding_model, config.embedding_dim, config.batch_size)


def get_shared_engine(config: MemoryConfig) -> "EmbeddingEngine":
    """Return the process-wide engine matching ``config``.

    Args:
        config: Memory configuration. Configs that agree on model,
            dimensionality and batch size share one engine.

    Returns:
        A shared, ready `EmbeddingEngine`.
    """
    key = engine_cache_key(config)
    with _shared_engines_lock:
        engine = _shared_engines.get(key)
        if engine is None:
            engine = EmbeddingEngine(config)
            _shared_engines[key] = engine
            logger.info(f"[EmbeddingEngine] shared engine cached for {key}")
        return engine


def reset_shared_engines() -> None:
    """Drop the cached engines. For tests only."""
    with _shared_engines_lock:
        _shared_engines.clear()
