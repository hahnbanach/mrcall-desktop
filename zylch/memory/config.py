"""Configuration for ZylchMemory."""

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class ZylchMemoryConfig(BaseSettings):
    """Configuration for ZylchMemory system.

    All settings can be overridden via environment variables with prefix ZYLCH_MEMORY_
    Example: ZYLCH_MEMORY_DB_PATH=/custom/path/memory.db
    """

    # Storage paths
    db_path: Path = Field(
        default=Path(".swarm/zylch_memory.db"),
        description="SQLite database file path"
    )
    index_dir: Path = Field(
        default=Path(".swarm/indices"),
        description="Directory for HNSW index files"
    )

    # Embedding model
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Sentence-transformers model name"
    )
    embedding_dim: int = Field(
        default=384,
        description="Embedding vector dimensionality"
    )
    embedding_device: Optional[str] = Field(
        default=None,
        description="Device for embedding model (None = auto, 'cpu', 'cuda')"
    )

    # HNSW index parameters
    hnsw_max_elements: int = Field(
        default=100000,
        description="Maximum elements per HNSW index"
    )
    hnsw_ef_construction: int = Field(
        default=200,
        description="ef_construction parameter (higher = better accuracy, slower build)"
    )
    hnsw_M: int = Field(
        default=16,
        description="M parameter (connections per node, higher = better accuracy, more memory)"
    )
    hnsw_ef_search: int = Field(
        default=50,
        description="ef parameter for search (higher = better recall, slower query)"
    )

    # Confidence learning
    confidence_alpha: float = Field(
        default=0.3,
        description="Reinforcement factor for positive feedback"
    )
    confidence_beta: float = Field(
        default=0.7,
        description="Penalty factor for negative feedback"
    )
    min_confidence_threshold: float = Field(
        default=0.0,
        description="Minimum confidence for pattern retrieval"
    )

    # Memory reconsolidation
    similarity_threshold: float = Field(
        default=0.85,
        description="Cosine similarity threshold to consider two memories as 'the same' (0.85 = conservative)"
    )
    confidence_boost_on_update: float = Field(
        default=0.1,
        description="Confidence increment when a memory is reinforced via reconsolidation"
    )

    # Hybrid search settings
    reconsolidation_threshold: float = Field(
        default=0.65,
        description="Minimum hybrid score to trigger reconsolidation"
    )
    fts_weight: float = Field(
        default=0.5,
        description="Default FTS weight (alpha) for hybrid search. 0=semantic only, 1=FTS only"
    )
    top_k_sentences: int = Field(
        default=3,
        description="Number of matching sentences to return per blob"
    )
    llm_merge_enabled: bool = Field(
        default=True,
        description="Enable LLM-assisted merge for reconsolidation"
    )
    llm_merge_model: str = Field(
        default="claude-3-5-haiku-20241022",
        description="Model for LLM merge"
    )

    # Performance
    batch_size: int = Field(
        default=32,
        description="Batch size for embedding generation"
    )
    cache_embeddings: bool = Field(
        default=True,
        description="Cache embeddings in SQLite to avoid recomputation"
    )

    # Namespace
    user_pattern_boost: float = Field(
        default=1.5,
        description="Score multiplier for user-specific patterns vs global"
    )

    class Config:
        env_prefix = "ZYLCH_MEMORY_"
        case_sensitive = False
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Ignore extra fields from .env (e.g., Zylch settings)


# Global default config instance
default_config = ZylchMemoryConfig()
