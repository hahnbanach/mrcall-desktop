"""Hybrid search: in-memory numpy vector search + LIKE text search."""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .embeddings import EmbeddingEngine
from .pattern_detection import detect_pattern
from zylch.storage.models import Blob, BlobSentence

logger = logging.getLogger(__name__)


def extract_identifiers_section(content: str) -> str:
    """Extract #IDENTIFIERS section from blob content.

    FTS should only match against entity identifiers (names, types),
    not the semantic content in #ABOUT or #HISTORY.

    Returns:
        The #IDENTIFIERS section content, or full content
        if no section found.
    """
    match = re.search(r"#IDENTIFIERS(.*?)#ABOUT", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return content


DEFAULT_FTS_WEIGHT = 0.5


@dataclass
class SearchResult:
    blob_id: str
    content: str
    namespace: str
    fts_score: float
    semantic_score: float
    exact_score: float
    hybrid_score: float
    events: list
    matching_sentences: List[str] = field(default_factory=list)


class InMemoryVectorIndex:
    """Brute-force cosine similarity over numpy arrays.

    For <10k blobs x 384 dims, search is <1ms after initial load.
    Memory: ~750KB for 500 blobs.
    """

    def __init__(self):
        self._matrix: Optional[np.ndarray] = None  # (N, 384)
        self._ids: Optional[List[str]] = None
        self._norms: Optional[np.ndarray] = None
        self._owner_id: Optional[str] = None
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
        self._owner_id = None
        self._count = 0

    def load(
        self,
        blobs: List[Tuple[str, bytes]],
        owner_id: str,
    ):
        """Load embeddings from (id, embedding_bytes) pairs.

        Args:
            blobs: list of (blob_id, embedding_bytes) tuples
            owner_id: owner for cache key
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

        self._owner_id = owner_id
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


class HybridSearchEngine:
    """Hybrid search: numpy vector similarity + LIKE text search."""

    RECONSOLIDATION_THRESHOLD = 0.65

    def __init__(
        self,
        get_session,
        embedding_engine: EmbeddingEngine,
        default_alpha: float = 0.5,
    ):
        self._get_session = get_session
        self.embeddings = embedding_engine
        self.default_alpha = default_alpha
        self._index = InMemoryVectorIndex()

    def invalidate_cache(self):
        """Invalidate vector index cache after mutations."""
        self._index.invalidate()

    def _ensure_index(self, owner_id: str):
        """Load vector index from DB if not cached."""
        if self._index.is_loaded and self._index._owner_id == owner_id:
            return

        logger.debug(f"[HybridSearch] loading vector index " f"for owner={owner_id}")
        with self._get_session() as session:
            rows = session.query(Blob.id, Blob.embedding).filter(Blob.owner_id == owner_id).all()
        blobs = [(str(r.id), r.embedding) for r in rows]
        self._index.load(blobs, owner_id)

    def _text_search(
        self,
        owner_id: str,
        query: str,
        namespace: Optional[str] = None,
    ) -> Dict[str, float]:
        """LIKE-based text search on blob content.

        Returns dict of blob_id -> normalized score (0-1).
        """
        if not query or not query.strip():
            return {}

        # Split query into terms for multi-term matching
        terms = [t.strip().lower() for t in query.split() if t.strip()]
        if not terms:
            return {}

        logger.debug(f"[HybridSearch] text_search: " f"terms={terms}, namespace={namespace}")

        with self._get_session() as session:
            q = session.query(Blob.id, Blob.content).filter(Blob.owner_id == owner_id)
            if namespace:
                q = q.filter(Blob.namespace == namespace)
            rows = q.all()

        scores: Dict[str, float] = {}
        for row in rows:
            identifiers = extract_identifiers_section(row.content or "").lower()
            matched = sum(1 for t in terms if t in identifiers)
            if matched > 0:
                score = matched / len(terms)
                scores[str(row.id)] = score

        logger.debug(f"[HybridSearch] text_search: " f"{len(scores)} matches")
        return scores

    def _exact_match_score(
        self,
        content: str,
        pattern: Optional[str],
    ) -> float:
        """Compute exact match score for identifier pattern.

        Returns 1.0 if pattern matches blob identifiers, else 0.0.
        """
        if not pattern:
            return 0.0
        identifiers = extract_identifiers_section(content).lower()
        return 1.0 if pattern.lower() in identifiers else 0.0

    def search(
        self,
        owner_id: str,
        query: str,
        namespace: Optional[str] = None,
        limit: int = 10,
        alpha: Optional[float] = None,
    ) -> List[SearchResult]:
        """Execute hybrid search.

        Args:
            owner_id: Owner ID
            query: Search query
            namespace: Optional namespace filter
            limit: Max results
            alpha: FTS weight (0=semantic only, 1=FTS only)

        Returns:
            List of SearchResult sorted by hybrid_score desc
        """
        fts_weight = alpha if alpha is not None else self.default_alpha

        # Detect identifier pattern for exact matching
        pattern = detect_pattern(query)
        exact_pattern = pattern.value if pattern else None

        logger.debug(
            f"[HybridSearch] search: query_len={len(query)}, "
            f"namespace={namespace}, alpha={fts_weight}, "
            f"exact_pattern={exact_pattern}"
        )

        # 1. Encode query
        query_embedding = self.embeddings.encode(query)

        # 2. Vector search
        self._ensure_index(owner_id)
        vec_results = self._index.search(query_embedding, top_k=limit * 3)
        vec_scores = dict(vec_results)

        # 3. Text search (on #IDENTIFIERS section)
        fts_query = extract_identifiers_section(query)
        fts_scores = self._text_search(owner_id, fts_query, namespace)

        # 4. Merge candidate IDs
        all_ids = set(vec_scores.keys()) | set(fts_scores.keys())

        if not all_ids:
            logger.debug("[HybridSearch] search returned no results")
            return []

        # 5. Load blob data for candidates
        with self._get_session() as session:
            q = session.query(Blob).filter(
                Blob.id.in_(list(all_ids)),
                Blob.owner_id == owner_id,
            )
            if namespace:
                q = q.filter(Blob.namespace == namespace)
            blobs = {str(b.id): b.to_dict() for b in q.all()}

        # 6. Score and rank
        scored: List[SearchResult] = []
        for bid in all_ids:
            blob_data = blobs.get(bid)
            if not blob_data:
                continue

            sem_score = vec_scores.get(bid, 0.0)
            fts_score = fts_scores.get(bid, 0.0)
            exact = self._exact_match_score(blob_data["content"], exact_pattern)

            # Hybrid: alpha * FTS + (1-alpha) * semantic
            hybrid = fts_weight * fts_score + (1 - fts_weight) * sem_score
            # Boost with exact match
            if exact > 0:
                hybrid = max(hybrid, exact)

            scored.append(
                SearchResult(
                    blob_id=bid,
                    content=blob_data["content"],
                    namespace=blob_data["namespace"],
                    fts_score=fts_score,
                    semantic_score=sem_score,
                    exact_score=exact,
                    hybrid_score=hybrid,
                    events=blob_data.get("events", []),
                )
            )

        scored.sort(key=lambda r: r.hybrid_score, reverse=True)
        scored = scored[:limit]

        # 7. Get matching sentences for top results
        for result in scored:
            result.matching_sentences = self._get_matching_sentences(
                result.blob_id,
                owner_id,
                query_embedding,
            )

        # Debug log scores
        for r in scored:
            logger.debug(
                f"Result blob_id={r.blob_id}:\n"
                f"{r.content[:80]}...\n"
                f"FTS: {r.fts_score:.3f}, "
                f"semantic: {r.semantic_score:.3f}, "
                f"exact: {r.exact_score:.3f}, "
                f"hybrid: {r.hybrid_score:.3f}"
            )

        return scored

    def find_for_reconsolidation(
        self,
        owner_id: str,
        content: str,
        namespace: str,
    ) -> Optional[SearchResult]:
        """Find existing blob for reconsolidation.

        Returns blob if hybrid_score > RECONSOLIDATION_THRESHOLD.
        """
        logger.debug(f"Reconsolidation search query: {content[:80]}")

        results = self.search(
            owner_id=owner_id,
            query=content,
            namespace=namespace,
            limit=5,
            alpha=0.5,
        )

        if not results:
            logger.debug("Reconsolidation: No results from hybrid search")
            return None

        top_result = results[0]
        logger.debug(
            f"Reconsolidation: Top result "
            f"blob_id={top_result.blob_id}, "
            f"hybrid={top_result.hybrid_score:.3f}, "
            f"fts={top_result.fts_score:.3f}, "
            f"semantic={top_result.semantic_score:.3f}"
        )

        if top_result.hybrid_score >= self.RECONSOLIDATION_THRESHOLD:
            logger.debug(
                f"Reconsolidation: MATCH "
                f"(score {top_result.hybrid_score:.3f} "
                f">= {self.RECONSOLIDATION_THRESHOLD})"
            )
            return top_result

        logger.debug(
            f"Reconsolidation: NO MATCH "
            f"(score {top_result.hybrid_score:.3f} "
            f"< {self.RECONSOLIDATION_THRESHOLD})"
        )
        return None

    def find_candidates_for_reconsolidation(
        self,
        owner_id: str,
        content: str,
        namespace: str,
        limit: int = 3,
    ) -> List[SearchResult]:
        """Find top candidate blobs for reconsolidation.

        Returns list of candidates above threshold.
        """
        logger.debug("Finding reconsolidation candidates for content")

        results = self.search(
            owner_id=owner_id,
            query=content,
            namespace=namespace,
            limit=limit,
            alpha=0.5,
        )

        candidates = [r for r in results if r.hybrid_score >= self.RECONSOLIDATION_THRESHOLD]

        logger.debug(
            f"Found {len(candidates)} candidates above "
            f"threshold {self.RECONSOLIDATION_THRESHOLD}"
        )
        for i, c in enumerate(candidates, 1):
            logger.debug(f"  Candidate {i}: blob_id={c.blob_id}, " f"hybrid={c.hybrid_score:.3f}")

        return candidates

    def _get_matching_sentences(
        self,
        blob_id: str,
        owner_id: str,
        query_embedding: np.ndarray,
        top_k: int = 3,
    ) -> List[str]:
        """Get top-k matching sentences from a blob.

        Deserializes sentence embeddings from LargeBinary
        and computes cosine similarity.
        """
        with self._get_session() as session:
            sentences = (
                session.query(
                    BlobSentence.sentence_text,
                    BlobSentence.embedding,
                )
                .filter(
                    BlobSentence.blob_id == blob_id,
                    BlobSentence.owner_id == owner_id,
                )
                .all()
            )

        if not sentences:
            return []

        query_norm = np.linalg.norm(query_embedding)
        if query_norm == 0:
            return []

        scored = []
        for s in sentences:
            if s.embedding is None:
                continue
            emb = np.frombuffer(s.embedding, dtype=np.float32)
            if emb.size == 0:
                continue
            emb_norm = np.linalg.norm(emb)
            if emb_norm == 0:
                continue
            sim = float(np.dot(query_embedding, emb) / (query_norm * emb_norm))
            scored.append((sim, s.sentence_text))

        scored.sort(reverse=True)
        return [text_val for _, text_val in scored[:top_k]]
