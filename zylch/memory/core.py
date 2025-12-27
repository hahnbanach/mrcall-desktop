"""Core ZylchMemory class - main API."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .config import ZylchMemoryConfig, default_config
from .embeddings import EmbeddingEngine
from .index import VectorIndex
from .storage import Storage

logger = logging.getLogger(__name__)


class ZylchMemory:
    """Unified memory system for AI agents with semantic search.

    Combines pattern learning, behavioral memory, and semantic search
    using vector embeddings and HNSW indexing.
    """

    def __init__(self, config: Optional[ZylchMemoryConfig] = None):
        """Initialize ZylchMemory.

        Args:
            config: Configuration (uses default if None)
        """
        self.config = config or default_config

        # Initialize components
        logger.info("Initializing ZylchMemory...")

        self.embedding_engine = EmbeddingEngine(self.config)
        self.storage = Storage(self.config)

        # HNSW indices per namespace (lazy-loaded)
        self._indices: Dict[str, VectorIndex] = {}

        # Load existing indices
        self._load_indices()

        logger.info("ZylchMemory initialized successfully")

    def _get_or_create_index(self, namespace: str) -> VectorIndex:
        """Get or create HNSW index for namespace.

        Args:
            namespace: Namespace identifier

        Returns:
            VectorIndex instance
        """
        if namespace not in self._indices:
            index = VectorIndex(namespace, self.config)

            # Try to load from disk
            index_path = self.config.index_dir / f"{namespace}.hnsw"
            if index_path.exists():
                index.load(index_path)
            else:
                # Rebuild from storage
                self._rebuild_index(namespace, index)

            self._indices[namespace] = index

        return self._indices[namespace]

    def _rebuild_index(self, namespace: str, index: VectorIndex) -> None:
        """Rebuild HNSW index from storage.

        Args:
            namespace: Namespace
            index: VectorIndex to populate
        """
        logger.info(f"Rebuilding index for namespace: {namespace}")

        # Get all embeddings for patterns
        pattern_embeddings = self.storage.get_all_embeddings_for_namespace(namespace, "patterns")

        # Get all embeddings for memories
        memory_embeddings = self.storage.get_all_embeddings_for_namespace(namespace, "memories")

        # Add to index
        all_embeddings = pattern_embeddings + memory_embeddings

        if all_embeddings:
            ids = [item[0] for item in all_embeddings]
            vectors = np.array([item[1] for item in all_embeddings])
            index.add_batch(vectors, ids)

            logger.info(f"Rebuilt index with {len(all_embeddings)} embeddings")

    def _load_indices(self) -> None:
        """Load all existing indices from disk."""
        if not self.config.index_dir.exists():
            return

        for index_file in self.config.index_dir.glob("*.hnsw"):
            namespace = index_file.stem
            logger.info(f"Found index for namespace: {namespace}")
            # Indices are lazy-loaded on first access

    def _get_or_create_embedding(self, text: str) -> tuple[int, np.ndarray]:
        """Get or create embedding for text (with caching).

        Args:
            text: Text to embed

        Returns:
            (embedding_id, vector)
        """
        if self.config.cache_embeddings:
            # Try cache first
            cached = self.storage.get_embedding(text, self.config.embedding_model)
            if cached:
                return cached

        # Generate new embedding
        vector = self.embedding_engine.encode(text)

        # Store in cache
        embedding_id = self.storage.store_embedding(
            text, vector, self.config.embedding_model
        )

        return embedding_id, vector

    def store_pattern(
        self,
        namespace: str,
        skill: str,
        intent: str,
        context: Dict[str, Any],
        action: Dict[str, Any],
        outcome: str,
        user_id: Optional[str] = None,
        confidence: float = 0.5
    ) -> str:
        """Store a pattern with automatic embedding and indexing.

        Args:
            namespace: Namespace (e.g., "user:mario" or "global:skills")
            skill: Skill name
            intent: User's natural language intent
            context: Context metadata
            action: Action taken (for replication)
            outcome: Outcome ("approved", "rejected", "modified")
            user_id: User identifier
            confidence: Initial confidence [0, 1]

        Returns:
            Pattern ID (as string)
        """
        # Generate embedding
        embedding_id, vector = self._get_or_create_embedding(intent)

        # Store in database
        pattern_id = self.storage.store_pattern(
            namespace=namespace,
            skill=skill,
            intent=intent,
            context=context,
            action=action,
            outcome=outcome,
            user_id=user_id,
            embedding_id=embedding_id,
            confidence=confidence
        )

        # Add to HNSW index
        index = self._get_or_create_index(namespace)
        index.add(vector, pattern_id)

        logger.debug(f"Stored pattern: id={pattern_id}, namespace={namespace}, skill={skill}")

        return str(pattern_id)

    def retrieve_similar_patterns(
        self,
        intent: str,
        skill: str,
        user_id: Optional[str] = None,
        limit: int = 5,
        min_confidence: float = 0.0
    ) -> List[Dict[str, Any]]:
        """Retrieve similar patterns using semantic search.

        Implements cascading retrieval: user patterns first, then global fallback.

        Args:
            intent: Search query (natural language)
            skill: Filter by skill
            user_id: User ID for personalized search
            limit: Max results
            min_confidence: Minimum confidence threshold

        Returns:
            List of patterns sorted by score (similarity × confidence)
        """
        # Generate query embedding
        _, query_vector = self._get_or_create_embedding(intent)

        results = []

        # Step 1: Search user-specific patterns
        if user_id:
            user_namespace = f"user:{user_id}"
            user_results = self._search_namespace(
                namespace=user_namespace,
                query_vector=query_vector,
                skill=skill,
                limit=limit,
                min_confidence=min_confidence
            )

            # Boost user patterns
            for result in user_results:
                result['score'] *= self.config.user_pattern_boost
                result['source'] = 'user'

            results.extend(user_results)

        # Step 2: Search global patterns (if needed)
        if len(results) < limit:
            global_namespace = "global:skills"
            global_results = self._search_namespace(
                namespace=global_namespace,
                query_vector=query_vector,
                skill=skill,
                limit=limit - len(results),
                min_confidence=min_confidence
            )

            for result in global_results:
                result['source'] = 'global'

            results.extend(global_results)

        # Sort by score
        results.sort(key=lambda x: x['score'], reverse=True)

        return results[:limit]

    def _search_namespace(
        self,
        namespace: str,
        query_vector: np.ndarray,
        skill: str,
        limit: int,
        min_confidence: float
    ) -> List[Dict[str, Any]]:
        """Search within a single namespace.

        Args:
            namespace: Namespace to search
            query_vector: Query embedding
            skill: Skill filter
            limit: Max results
            min_confidence: Confidence threshold

        Returns:
            List of matching patterns
        """
        # Get index
        try:
            index = self._get_or_create_index(namespace)
        except Exception as e:
            logger.warning(f"Failed to get index for {namespace}: {e}")
            return []

        if index.size == 0:
            return []

        # HNSW search
        labels, distances = index.search(query_vector, k=min(limit * 2, index.size))

        # Fetch patterns from storage
        results = []
        for label, distance in zip(labels, distances):
            pattern = self.storage.get_pattern(int(label))

            if not pattern:
                continue

            # Filter by skill
            if pattern['skill'] != skill:
                continue

            # Filter by confidence
            if pattern['confidence'] < min_confidence:
                continue

            # Calculate similarity (1 - distance)
            similarity = 1.0 - distance

            # Combined score
            score = similarity * pattern['confidence']

            pattern['similarity'] = similarity
            pattern['score'] = score

            results.append(pattern)

        return results

    def update_confidence(self, pattern_id: str, success: bool) -> None:
        """Update pattern confidence using Bayesian learning.

        Args:
            pattern_id: Pattern ID
            success: True = reinforce, False = penalize
        """
        pattern = self.storage.get_pattern(int(pattern_id))

        if not pattern:
            logger.warning(f"Pattern not found: {pattern_id}")
            return

        current_confidence = pattern['confidence']

        # Bayesian update
        if success:
            # Positive reinforcement
            new_confidence = current_confidence + (1 - current_confidence) * self.config.confidence_alpha
        else:
            # Penalty
            new_confidence = current_confidence * self.config.confidence_beta

        # Clamp [0, 1]
        new_confidence = max(0.0, min(1.0, new_confidence))

        # Update storage
        self.storage.update_pattern_confidence(int(pattern_id), new_confidence)

        logger.debug(
            f"Updated confidence: pattern_id={pattern_id}, "
            f"{current_confidence:.3f} → {new_confidence:.3f}"
        )

    def _find_similar_memories(
        self,
        namespace: str,
        category: str,
        query_vector: np.ndarray,
        threshold: float
    ) -> List[Dict[str, Any]]:
        """Find memories similar to query vector in given namespace/category.

        Args:
            namespace: Namespace to search
            category: Category filter
            query_vector: Query embedding vector
            threshold: Minimum cosine similarity threshold

        Returns:
            List of similar memories with 'similarity' field, sorted by similarity DESC
        """
        # Get all memories in namespace/category
        memories = self.storage.get_memories_by_namespace(namespace, category, limit=1000)

        if not memories:
            return []

        results = []
        for mem in memories:
            if mem.get('embedding_id') is None:
                continue

            # Get embedding vector for this memory
            mem_vector = self.storage.get_embedding_by_id(mem['embedding_id'])
            if mem_vector is None:
                continue

            # Compute cosine similarity
            # cosine_sim = dot(a, b) / (norm(a) * norm(b))
            dot_product = np.dot(query_vector, mem_vector)
            norm_query = np.linalg.norm(query_vector)
            norm_mem = np.linalg.norm(mem_vector)

            if norm_query == 0 or norm_mem == 0:
                continue

            similarity = dot_product / (norm_query * norm_mem)

            if similarity >= threshold:
                mem['similarity'] = float(similarity)
                results.append(mem)

        # Sort by similarity DESC
        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results

    def store_memory(
        self,
        namespace: str,
        category: str,
        context: str,
        pattern: str,
        examples: List[str],
        user_id: Optional[str] = None,
        confidence: float = 0.5,
        force_new: bool = False
    ) -> str:
        """Store or update behavioral memory with reconsolidation.

        If a similar memory exists (cosine > threshold), UPDATE it instead of creating new.
        This mimics human memory reconsolidation: updating existing memories rather than
        creating parallel conflicting ones.

        Args:
            namespace: Namespace
            category: Category ("email", "contacts", "calendar", "task", "general")
            context: Context description
            pattern: Pattern description
            examples: List of example IDs
            user_id: User identifier
            confidence: Initial confidence (used only for new memories)
            force_new: If True, skip similarity check and always create new memory

        Returns:
            Memory ID (existing if reconsolidated, new if created)
        """
        # Generate embedding from context + pattern
        text = f"{context} {pattern}"
        embedding_id, vector = self._get_or_create_embedding(text)

        # Check for similar existing memories (unless forced new)
        if not force_new:
            similar = self._find_similar_memories(
                namespace=namespace,
                category=category,
                query_vector=vector,
                threshold=self.config.similarity_threshold
            )

            if similar:
                # RECONSOLIDATE: Update the most similar existing memory
                existing = similar[0]
                logger.info(
                    f"Reconsolidating memory {existing['id']} "
                    f"(similarity={existing['similarity']:.3f}, threshold={self.config.similarity_threshold})"
                )

                # Update the memory with new content
                self.storage.update_memory(
                    memory_id=existing['id'],
                    pattern=pattern,
                    context=context,
                    examples=examples,
                    confidence_delta=self.config.confidence_boost_on_update,
                    new_embedding_id=embedding_id
                )

                # Note: HNSW index update is tricky (doesn't support in-place update)
                # For now, the old vector position remains; periodic index rebuild can fix this
                # Alternative: delete old ID and add new position (not implemented here for simplicity)

                logger.debug(
                    f"Reconsolidated memory: id={existing['id']}, "
                    f"namespace={namespace}, category={category}"
                )

                return str(existing['id'])

        # No similar found (or force_new): INSERT new memory
        memory_id = self.storage.store_memory(
            namespace=namespace,
            category=category,
            context=context,
            pattern=pattern,
            examples=examples,
            embedding_id=embedding_id,
            confidence=confidence
        )

        # Add to HNSW index
        index = self._get_or_create_index(namespace)
        index.add(vector, memory_id)

        logger.debug(f"Stored new memory: id={memory_id}, namespace={namespace}, category={category}")

        return str(memory_id)

    def retrieve_memories(
        self,
        query: str,
        category: Optional[str] = None,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Retrieve behavioral memories using semantic search.

        Args:
            query: Search query (natural language)
            category: Optional category filter
            user_id: User ID for personalized search (deprecated, use namespace)
            namespace: Explicit namespace (e.g., "business", "person:email@example.com")
            limit: Max results

        Returns:
            List of memories sorted by similarity
        """
        # Generate query embedding
        _, query_vector = self._get_or_create_embedding(query)

        # Determine namespace (explicit namespace takes precedence)
        if namespace is None:
            namespace = f"user:{user_id}" if user_id else "global:system"

        # Get index
        index = self._get_or_create_index(namespace)

        if index.size == 0:
            return []

        # HNSW search
        labels, distances = index.search(query_vector, k=limit * 2)

        # Fetch from storage
        memories = self.storage.get_memories_by_namespace(namespace, category, limit=100)

        # Match and score
        results = []
        label_set = set(labels)

        for memory in memories:
            if memory['id'] not in label_set:
                continue

            # Get distance
            idx = labels.index(memory['id'])
            distance = distances[idx]

            memory['similarity'] = 1.0 - distance
            results.append(memory)

        # Sort by similarity
        results.sort(key=lambda x: x['similarity'], reverse=True)

        return results[:limit]

    def save_indices(self) -> None:
        """Save all HNSW indices to disk."""
        for namespace, index in self._indices.items():
            index_path = self.config.index_dir / f"{namespace}.hnsw"
            index.save(index_path)

    def close(self) -> None:
        """Close storage and save indices."""
        logger.info("Closing ZylchMemory...")

        # Save indices
        self.save_indices()

        # Close storage
        self.storage.close()

        logger.info("ZylchMemory closed")
