"""Hybrid search combining FTS and semantic search."""

import json
import logging
import re
from dataclasses import dataclass
from typing import List, Optional
import numpy as np

from .embeddings import EmbeddingEngine
from .pattern_detection import detect_pattern

logger = logging.getLogger(__name__)


def extract_identifiers_section(content: str) -> str:
    """Extract #IDENTIFIERS section from blob content for FTS matching.

    FTS should only match against entity identifiers (names, types),
    not the semantic content in #ABOUT or #HISTORY.

    Returns:
        The #IDENTIFIERS section content, or full content if no section found.
    """
    match = re.search(r'#IDENTIFIERS(.*?)#ABOUT', content, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: if no #IDENTIFIERS/#ABOUT structure, use full content
    return content

DEFAULT_FTS_WEIGHT = 0.5  # Configurable balance between FTS and semantic

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
    matching_sentences: List[str]

class HybridSearchEngine:
    """Hybrid search engine for entity blobs."""

    RECONSOLIDATION_THRESHOLD = 0.65

    def __init__(self, supabase_client, embedding_engine: EmbeddingEngine, default_alpha: float = 0.5):
        self.supabase = supabase_client
        self.embeddings = embedding_engine
        self.default_alpha = default_alpha

    def search(
        self,
        owner_id: str,
        query: str,
        namespace: Optional[str] = None,
        limit: int = 10,
        alpha: Optional[float] = None
    ) -> List[SearchResult]:
        """Execute hybrid search.

        Args:
            owner_id: Firebase UID
            query: Search query
            namespace: Optional namespace filter
            limit: Max results
            alpha: FTS weight (0-1). Default from config.

        Returns:
            List of SearchResult
        """
        fts_weight = alpha if alpha is not None else self.default_alpha

        # Detect identifier pattern for exact matching
        pattern = detect_pattern(query)
        exact_pattern = pattern.value if pattern else None

        # Generate query embedding (uses full query for semantic search)
        query_embedding = self.embeddings.encode(query)

        # Extract #IDENTIFIERS section for FTS (matches stored tsv which also uses only #IDENTIFIERS)
        fts_query = extract_identifiers_section(query)

        # Build RPC params - always include p_exact_pattern (can be NULL)
        rpc_params = {
            "p_owner_id": owner_id,
            "p_query": fts_query,  # FTS uses only #IDENTIFIERS section
            "p_query_embedding": query_embedding.tolist(),  # Semantic uses full query
            "p_namespace": namespace,
            "p_fts_weight": fts_weight,
            "p_limit": limit,
            "p_exact_pattern": exact_pattern,  # None becomes SQL NULL
        }

        # Debug: Log FTS query (extracted identifiers only)
        logger.debug(f"FTS query (extracted #IDENTIFIERS):\n{fts_query}")
        logger.debug(f"Exact pattern: {exact_pattern}")

        # Call Supabase hybrid search function
        result = self.supabase.rpc(
            "hybrid_search_blobs",
            rpc_params
        ).execute()

        # Debug: Log FTS scores for each result (full content)
        for row in result.data or []:
            logger.debug(
                f"Result blob_id={row['blob_id']}:\n{row['content']}\n"
                f"FTS: {row['fts_score']:.3f}, semantic: {row['semantic_score']:.3f}, "
                f"exact: {row.get('exact_score', 0):.3f}, hybrid: {row['hybrid_score']:.3f}\n"
                f"---"
            )

        # Get matching sentences for each result
        results = []
        for row in result.data or []:
            sentences = self._get_matching_sentences(
                row["blob_id"],
                owner_id,
                query_embedding
            )
            results.append(SearchResult(
                blob_id=row["blob_id"],
                content=row["content"],
                namespace=row["namespace"],
                fts_score=row["fts_score"],
                semantic_score=row["semantic_score"],
                exact_score=row.get("exact_score", 0.0),
                hybrid_score=row["hybrid_score"],
                events=row["events"],
                matching_sentences=sentences
            ))

        return results

    def find_for_reconsolidation(
        self,
        owner_id: str,
        content: str,
        namespace: str
    ) -> Optional[SearchResult]:
        """Find existing blob for reconsolidation.

        Returns blob if hybrid_score > RECONSOLIDATION_THRESHOLD.
        """
        logger.debug(f"Reconsolidation search query: {content}")

        results = self.search(
            owner_id=owner_id,
            query=content,
            namespace=namespace,
            limit=5,  # Get top 5 to see alternatives in logs
            alpha=0.5  # Balanced for reconsolidation
        )

        if not results:
            logger.debug("Reconsolidation: No results from hybrid search")
            return None

        top_result = results[0]
        logger.debug(
            f"Reconsolidation: Top result blob_id={top_result.blob_id}, "
            f"hybrid={top_result.hybrid_score:.3f}, fts={top_result.fts_score:.3f}, "
            f"semantic={top_result.semantic_score:.3f}"
        )

        if top_result.hybrid_score >= self.RECONSOLIDATION_THRESHOLD:
            logger.debug(
                f"Reconsolidation: MATCH (score {top_result.hybrid_score:.3f} >= {self.RECONSOLIDATION_THRESHOLD})"
            )
            return top_result

        logger.debug(
            f"Reconsolidation: NO MATCH (score {top_result.hybrid_score:.3f} < {self.RECONSOLIDATION_THRESHOLD})"
        )
        return None

    def find_candidates_for_reconsolidation(
        self,
        owner_id: str,
        content: str,
        namespace: str,
        limit: int = 3
    ) -> List[SearchResult]:
        """Find top candidate blobs for reconsolidation (above threshold).

        Returns list of candidates to try merging with.
        """
        logger.debug("Finding reconsolidation candidates for content")

        results = self.search(
            owner_id=owner_id,
            query=content,
            namespace=namespace,
            limit=limit,
            alpha=0.5
        )

        # Filter by threshold
        candidates = [r for r in results if r.hybrid_score >= self.RECONSOLIDATION_THRESHOLD]

        logger.debug(f"Found {len(candidates)} candidates above threshold {self.RECONSOLIDATION_THRESHOLD}")
        for i, c in enumerate(candidates, 1):
            logger.debug(f"  Candidate {i}: blob_id={c.blob_id}, hybrid={c.hybrid_score:.3f}")

        return candidates

    def _get_matching_sentences(
        self,
        blob_id: str,
        owner_id: str,
        query_embedding: np.ndarray,
        top_k: int = 3
    ) -> List[str]:
        """Get top-k matching sentences from a blob."""
        sentences = self.supabase.table("blob_sentences")\
            .select("sentence_text, embedding")\
            .eq("blob_id", blob_id)\
            .eq("owner_id", owner_id)\
            .execute()

        if not sentences.data:
            return []

        # Compute similarities
        scored = []
        for s in sentences.data:
            # Supabase returns embedding as string, need to parse it
            emb_data = s["embedding"]
            if isinstance(emb_data, str):
                emb_data = json.loads(emb_data)
            emb = np.array(emb_data, dtype=np.float32)
            sim = float(np.dot(query_embedding, emb) /
                       (np.linalg.norm(query_embedding) * np.linalg.norm(emb)))
            scored.append((sim, s["sentence_text"]))

        # Return top-k
        scored.sort(reverse=True)
        return [text for _, text in scored[:top_k]]
