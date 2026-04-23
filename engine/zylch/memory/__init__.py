"""Memory system for zylch.

This module provides entity-centric memory storage using Supabase blobs.
The old SQLite-based ZylchMemory system has been removed.
"""

from .config import MemoryConfig
from .embeddings import EmbeddingEngine
from .blob_storage import BlobStorage
from .hybrid_search import (
    HybridSearchEngine,
    InMemoryVectorIndex,
    SearchResult,
)
from .llm_merge import LLMMergeService
from .text_processing import split_sentences
from .pattern_detection import detect_pattern

__all__ = [
    "MemoryConfig",
    "EmbeddingEngine",
    "BlobStorage",
    "HybridSearchEngine",
    "InMemoryVectorIndex",
    "SearchResult",
    "LLMMergeService",
    "split_sentences",
    "detect_pattern",
]
