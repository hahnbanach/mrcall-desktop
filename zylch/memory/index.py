"""HNSW vector indexing for fast similarity search."""

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import hnswlib
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from .config import ZylchMemoryConfig

logger = logging.getLogger(__name__)


class VectorIndex:
    """HNSW index for O(log n) approximate nearest neighbor search."""

    def __init__(self, namespace: str, config: ZylchMemoryConfig):
        """Initialize HNSW index for a namespace.

        Args:
            namespace: Namespace identifier (e.g., "user:mario")
            config: Configuration
        """
        self.namespace = namespace
        self.config = config
        self.dim = config.embedding_dim

        # Create HNSW index
        self.index = hnswlib.Index(space='cosine', dim=self.dim)

        # Initialize index
        self.index.init_index(
            max_elements=config.hnsw_max_elements,
            ef_construction=config.hnsw_ef_construction,
            M=config.hnsw_M,
            random_seed=42
        )

        # Set search ef
        self.index.set_ef(config.hnsw_ef_search)

        # Track current size
        self._size = 0

        # Fallback storage for brute-force search (used when index is too small for HNSW)
        self._vectors = []  # List of (label, vector) tuples
        self._use_fallback_threshold = 10  # Use brute-force for < 10 elements

        logger.info(
            f"Initialized HNSW index for namespace='{namespace}', "
            f"dim={self.dim}, max_elements={config.hnsw_max_elements}"
        )

    def add(self, embedding: np.ndarray, label: int) -> None:
        """Add single embedding to index.

        Args:
            embedding: Embedding vector (dim,)
            label: Unique identifier (typically pattern ID)
        """
        self.index.add_items([embedding], [label])
        self._vectors.append((label, embedding.copy()))
        self._size += 1

    def add_batch(self, embeddings: np.ndarray, labels: List[int]) -> None:
        """Add multiple embeddings in batch.

        Args:
            embeddings: Embedding matrix (n, dim)
            labels: List of unique identifiers
        """
        self.index.add_items(embeddings, labels)
        for label, vec in zip(labels, embeddings):
            self._vectors.append((label, vec.copy()))
        self._size += len(labels)

    def search(
        self, query_embedding: np.ndarray, k: int = 5
    ) -> Tuple[List[int], List[float]]:
        """Search for k nearest neighbors.

        Args:
            query_embedding: Query vector (dim,)
            k: Number of results

        Returns:
            (labels, distances): Lists of pattern IDs and cosine distances
        """
        if self._size == 0:
            return [], []

        # Adjust k if index has fewer elements
        k = min(k, self._size)

        # Use brute-force search for small indices to avoid HNSW errors
        if self._size < self._use_fallback_threshold:
            return self._brute_force_search(query_embedding, k)

        # Use HNSW for larger indices
        try:
            # Adjust ef_search based on actual size to avoid HNSW errors
            optimal_ef = max(k, min(k * 2, self._size))
            self.index.set_ef(optimal_ef)

            labels, distances = self.index.knn_query([query_embedding], k=k)
            return labels[0].tolist(), distances[0].tolist()
        except RuntimeError as e:
            # Fallback to brute-force if HNSW fails
            logger.warning(f"HNSW search failed, using brute-force: {e}")
            return self._brute_force_search(query_embedding, k)

    def _brute_force_search(
        self, query_embedding: np.ndarray, k: int
    ) -> Tuple[List[int], List[float]]:
        """Brute-force cosine similarity search for small indices.

        Args:
            query_embedding: Query vector (dim,)
            k: Number of results

        Returns:
            (labels, distances): Lists of pattern IDs and cosine distances
        """
        if not self._vectors:
            return [], []

        # Extract labels and vectors
        labels = [label for label, _ in self._vectors]
        vectors = np.array([vec for _, vec in self._vectors])

        # Compute cosine similarities
        similarities = cosine_similarity([query_embedding], vectors)[0]

        # Convert to distances (1 - similarity)
        distances = 1.0 - similarities

        # Get top-k
        top_k_indices = np.argsort(distances)[:k]

        return (
            [labels[i] for i in top_k_indices],
            [float(distances[i]) for i in top_k_indices]
        )

    def save(self, path: Path) -> None:
        """Save index to disk.

        Args:
            path: File path for index
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        self.index.save_index(str(path))
        logger.info(f"Saved HNSW index: {path}")

    def load(self, path: Path) -> None:
        """Load index from disk.

        Args:
            path: File path to index
        """
        if not path.exists():
            logger.warning(f"Index file not found: {path}")
            return

        self.index.load_index(str(path))
        self._size = self.index.get_current_count()
        logger.info(f"Loaded HNSW index: {path}, size={self._size}")

    @property
    def size(self) -> int:
        """Current number of elements in index."""
        return self._size
