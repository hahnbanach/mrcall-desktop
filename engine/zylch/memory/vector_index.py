"""Brute-force cosine similarity over numpy arrays — the in-memory vector index.

Moved out of ``hybrid_search.py`` unchanged; that module re-exports it under
the same name, so ``zylch.memory.InMemoryVectorIndex`` keeps resolving.
"""

import logging
import time
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class InMemoryVectorIndex:
    """Brute-force cosine similarity over numpy arrays.

    For <10k blobs x 384 dims, search is <1ms after initial load.
    Memory: ~750KB for 500 blobs.
    """

    def __init__(self):
        self._matrix: Optional[np.ndarray] = None  # (N, 384)
        self._ids: Optional[List[str]] = None
        self._norms: Optional[np.ndarray] = None
        # The scope this index was loaded for: "<owner_id>|<company_key>".
        # Two owners under one key see different rule rows, so the owner
        # stays part of the identity; two keys are two companies.
        self._scope_id: Optional[str] = None
        self._count: int = 0

    @property
    def is_loaded(self) -> bool:
        return self._matrix is not None

    def invalidate(self):
        """Clear cached index (call after blob insert/update)."""
        logger.debug("[VectorIndex] invalidate cache")
        self._matrix = None
        self._ids = None
        self._norms = None
        self._scope_id = None
        self._count = 0

    def load(
        self,
        blobs: List[Tuple[str, bytes]],
        scope_id: str,
    ):
        """Load embeddings from (id, embedding_bytes) pairs.

        Args:
            blobs: list of (blob_id, embedding_bytes) tuples
            scope_id: the (owner, key) scope these vectors were read for
        """
        t0 = time.perf_counter()
        ids = []
        vectors = []
        for blob_id, emb_bytes in blobs:
            if emb_bytes is None:
                continue
            vec = np.frombuffer(emb_bytes, dtype=np.float32)
            if vec.size == 0:
                continue
            ids.append(blob_id)
            vectors.append(vec)

        if vectors:
            self._matrix = np.vstack(vectors)
            self._norms = np.linalg.norm(self._matrix, axis=1)
            self._ids = ids
        else:
            self._matrix = None
            self._ids = []
            self._norms = None

        self._scope_id = scope_id
        self._count = len(ids)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(f"[VectorIndex] load: {self._count} vectors " f"in {elapsed_ms:.1f}ms")

    def search(
        self,
        query_vec: np.ndarray,
        top_k: int = 10,
    ) -> List[Tuple[str, float]]:
        """Return top-K (blob_id, cosine_similarity) pairs.

        Args:
            query_vec: query embedding (384,)
            top_k: max results

        Returns:
            List of (blob_id, score) sorted descending
        """
        if self._matrix is None or len(self._ids) == 0:
            return []
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []

        t0 = time.perf_counter()
        scores = np.dot(self._matrix, query_vec) / (self._norms * query_norm)
        top_idx = np.argsort(scores)[-top_k:][::-1]
        results = [(self._ids[i], float(scores[i])) for i in top_idx if scores[i] > 0]
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(
            f"[VectorIndex] search: top_k={top_k}, " f"found={len(results)} in {elapsed_ms:.2f}ms"
        )
        return results
