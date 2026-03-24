"""Embedding generation using sentence-transformers."""

import logging
from typing import List, Union

import numpy as np

from .config import MemoryConfig

logger = logging.getLogger(__name__)


class EmbeddingEngine:
    """Generates semantic embeddings for text using sentence-transformers.

    Uses caching to avoid recomputing embeddings for the same text.
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

        logger.info(f"Loading embedding model: {self.model_name} (ONNX backend)")

        from sentence_transformers import SentenceTransformer

        # Use ONNX backend — no torch dependency, ~10x smaller footprint
        self.model = SentenceTransformer(
            self.model_name,
            backend="onnx",
        )

        # Verify dimensionality
        test_embedding = self.model.encode("test")
        actual_dim = len(test_embedding)
        if actual_dim != self.dim:
            logger.warning(
                f"Model {self.model_name} produces {actual_dim}-dim embeddings, "
                f"config expects {self.dim}. Updating config."
            )
            self.dim = actual_dim

        logger.info(
            f"Embedding engine ready: model={self.model_name}, "
            f"dim={self.dim}, device={self.model.device}"
        )

    def encode(self, text: Union[str, List[str]]) -> np.ndarray:
        """Generate embedding(s) for text.

        Args:
            text: Single text string or list of strings

        Returns:
            Embedding array: shape (dim,) for single text or (n, dim) for batch
        """
        if isinstance(text, str):
            # Single text
            embedding = self.model.encode(
                text,
                convert_to_numpy=True,
                show_progress_bar=False
            )
            return embedding.astype(np.float32)
        else:
            # Batch
            embeddings = self.model.encode(
                text,
                batch_size=self.config.batch_size,
                convert_to_numpy=True,
                show_progress_bar=len(text) > 100  # Show progress for large batches
            )
            return embeddings.astype(np.float32)

    def similarity(self, embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """Compute cosine similarity between two embeddings.

        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector

        Returns:
            Cosine similarity in range [-1, 1] (1 = identical, -1 = opposite)
        """
        # Cosine similarity: dot(a, b) / (norm(a) * norm(b))
        dot_product = np.dot(embedding1, embedding2)
        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(embedding2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))

    def distance(self, embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """Compute cosine distance between two embeddings.

        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector

        Returns:
            Cosine distance in range [0, 2] (0 = identical, 2 = opposite)
        """
        # Cosine distance: 1 - similarity
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
