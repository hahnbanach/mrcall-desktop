# Entity-Centric Memory System Development Plan

## Executive Summary

This plan details the implementation of the entity-centric memory system for Zylch, evolving the current `zylch_memory` package from a basic semantic search implementation to a full hybrid search system with sentence-level embeddings, PostgreSQL FTS support, and LLM-assisted reconsolidation.

### Current State
- **Implemented**: Vector embeddings (all-MiniLM-L6-v2, 384 dims), HNSW indexing, basic reconsolidation (0.85 threshold, simple update), namespace isolation
- **Database**: Currently uses local SQLite in `zylch_memory/` package
- **Integration**: Used by `memory_worker.py`, `factory.py` tools, various services

### Target State
- Migrate to **Supabase PostgreSQL** with pgvector + ts_vector
- Hybrid search combining FTS with semantic search
- Sentence-level embeddings for precise matching
- New `blobs` and `blob_sentences` tables
- LLM-assisted merge for intelligent reconsolidation
- Configurable FTS/semantic weight (alpha) for hybrid search
- RESTful API endpoints for external access

---

## Phase 1: Database Schema (Supabase PostgreSQL)

**Dependencies**: None (foundation phase)

### 1.1 Schema Design

All data stored in Supabase with Row Level Security (RLS), scoped by `owner_id` (Firebase UID).

```sql
-- Enable extensions (if not already enabled)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ===========================================
-- Table: blobs (main entity memory storage)
-- ===========================================
CREATE TABLE blobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_id TEXT NOT NULL,  -- Firebase UID for multi-tenancy
    namespace TEXT NOT NULL,  -- e.g., "user:{uid}", "org:{org_id}", "shared:{recipient}:{sender}"
    content TEXT NOT NULL,
    embedding VECTOR(384),  -- blob-level embedding (optional, for pre-filter)
    tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    events JSONB DEFAULT '[]'::jsonb,  -- [{timestamp, description, source}]
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_blobs_owner ON blobs(owner_id);
CREATE INDEX idx_blobs_namespace ON blobs(owner_id, namespace);
CREATE INDEX idx_blobs_tsv ON blobs USING GIN(tsv);
CREATE INDEX idx_blobs_embedding ON blobs USING hnsw(embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);
CREATE INDEX idx_blobs_updated ON blobs(updated_at DESC);

-- RLS
ALTER TABLE blobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY blobs_owner_policy ON blobs
    FOR ALL USING (owner_id = current_setting('app.current_user_id', true));

-- ===========================================
-- Table: blob_sentences (sentence-level granularity)
-- ===========================================
CREATE TABLE blob_sentences (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    blob_id UUID NOT NULL REFERENCES blobs(id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL,  -- Denormalized for RLS
    sentence_text TEXT NOT NULL,
    embedding VECTOR(384) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_sentences_blob_id ON blob_sentences(blob_id);
CREATE INDEX idx_sentences_owner ON blob_sentences(owner_id);
CREATE INDEX idx_sentences_embedding ON blob_sentences USING hnsw(embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

-- RLS
ALTER TABLE blob_sentences ENABLE ROW LEVEL SECURITY;
CREATE POLICY sentences_owner_policy ON blob_sentences
    FOR ALL USING (owner_id = current_setting('app.current_user_id', true));

-- ===========================================
-- Helper functions
-- ===========================================

-- Hybrid search function
CREATE OR REPLACE FUNCTION hybrid_search_blobs(
    p_owner_id TEXT,
    p_query TEXT,
    p_query_embedding VECTOR(384),
    p_namespace TEXT DEFAULT NULL,
    p_fts_weight FLOAT DEFAULT 0.5,
    p_limit INT DEFAULT 10
)
RETURNS TABLE (
    blob_id UUID,
    content TEXT,
    namespace TEXT,
    fts_score FLOAT,
    semantic_score FLOAT,
    hybrid_score FLOAT,
    events JSONB
) AS $$
BEGIN
    RETURN QUERY
    WITH fts_results AS (
        SELECT
            b.id,
            b.content,
            b.namespace,
            b.events,
            ts_rank(b.tsv, plainto_tsquery('english', p_query)) AS fts_score
        FROM blobs b
        WHERE b.owner_id = p_owner_id
          AND (p_namespace IS NULL OR b.namespace = p_namespace)
          AND b.tsv @@ plainto_tsquery('english', p_query)
    ),
    semantic_results AS (
        SELECT
            bs.blob_id,
            MAX(1 - (bs.embedding <=> p_query_embedding)) AS max_semantic_score
        FROM blob_sentences bs
        WHERE bs.owner_id = p_owner_id
          AND bs.blob_id IN (SELECT id FROM fts_results)
        GROUP BY bs.blob_id
    )
    SELECT
        f.id AS blob_id,
        f.content,
        f.namespace,
        COALESCE(f.fts_score, 0)::FLOAT AS fts_score,
        COALESCE(s.max_semantic_score, 0)::FLOAT AS semantic_score,
        (p_fts_weight * COALESCE(f.fts_score, 0) +
         (1 - p_fts_weight) * COALESCE(s.max_semantic_score, 0))::FLOAT AS hybrid_score,
        f.events
    FROM fts_results f
    LEFT JOIN semantic_results s ON f.id = s.blob_id
    ORDER BY hybrid_score DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- Update timestamp trigger
CREATE OR REPLACE FUNCTION update_blob_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER blobs_updated_at
    BEFORE UPDATE ON blobs
    FOR EACH ROW
    EXECUTE FUNCTION update_blob_timestamp();
```

### 1.2 Migration Tasks

1. Create migration file: `zylch/storage/migrations/004_entity_memory_blobs.sql`
2. Run migration on Supabase staging
3. Verify RLS policies work with Firebase UIDs
4. Test hybrid search function with sample data

---

## Phase 2: Core Memory Package Updates

**Dependencies**: Phase 1 (schema must exist)

### 2.1 New Files to Create

| File | Purpose |
|------|---------|
| `zylch_memory/text_processing.py` | Sentence splitter with abbreviation handling |
| `zylch_memory/hybrid_search.py` | Hybrid FTS + semantic search engine |
| `zylch_memory/llm_merge.py` | LLM-assisted memory reconsolidation |
| `zylch_memory/blob_storage.py` | Blob CRUD with Supabase |

### 2.2 Sentence Splitter

**File**: `zylch_memory/zylch_memory/text_processing.py`

```python
"""Text processing utilities for memory system."""

import re
from typing import List

ABBREVIATIONS = {
    # Titles (EN/PT/ES/FR/IT/DE)
    'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr',
    'sra', 'srta',  # PT/ES
    'mme', 'mlle',  # FR
    'sig', 'dott', 'dottssa', 'ing', 'avv', 'arch',  # IT
    'herr', 'frau',  # DE

    # Corporate (EN/PT/ES/FR/IT/DE)
    'inc', 'ltd', 'corp', 'co', 'llc',
    'ltda', 'cia',  # PT/ES
    'sa', 'sarl', 'sas',  # FR (also ES/IT/PT)
    'srl', 'spa', 'snc', 'sas',  # IT
    'gmbh', 'ag', 'kg', 'ohg', 'ug',  # DE
    'sl', 'sau',  # ES

    # Latin/Common (universal)
    'vs', 'etc', 'eg', 'ie', 'al', 'cf', 'nb', 'ps', 'ca', 'approx',

    # Months - English
    'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'sept', 'oct', 'nov', 'dec',
    # Months - Portuguese
    'fev', 'abr', 'mai', 'ago', 'set', 'out', 'dez',
    # Months - Spanish
    'ene', 'abr', 'ago', 'dic',
    # Months - French
    'janv', 'févr', 'avr', 'juil', 'août', 'sept', 'déc',
    # Months - Italian
    'gen', 'mag', 'giu', 'lug', 'sett', 'ott', 'dic',
    # Months - German
    'jän', 'mär', 'mai', 'okt', 'dez',

    # Days (common abbreviations)
    'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun',
    'lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim',  # FR
    'lun', 'mié', 'jue', 'vie', 'sáb', 'dom',  # ES
    'seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom',  # PT
    'lun', 'gio', 'sab',  # IT
    'mo', 'di', 'mi', 'do', 'fr', 'sa', 'so',  # DE

    # Units/Misc
    'kg', 'km', 'cm', 'mm', 'ml', 'mg', 'nr', 'no', 'tel', 'fax', 'ext',
    'apt', 'st', 'ave', 'blvd', 'rd',
    'pag', 'vol', 'ed', 'cap', 'art', 'num',
}

def split_sentences(text: str) -> List[str]:
    """Split text into sentences, handling abbreviations and edge cases.

    Handles:
    - Abbreviations (Dr., Mr., Inc., etc.)
    - Decimal numbers (3.14)
    - Ellipsis (...)
    - URLs (preserved, not split)
    - Split on . ! ? only at sentence boundaries

    Returns:
        List of sentences preserving order
    """
    # Protect abbreviations
    protected = text
    for abbr in ABBREVIATIONS:
        pattern = rf'\b({abbr})\.(?=\s)'
        protected = re.sub(pattern, rf'\1<DOT>', protected, flags=re.IGNORECASE)

    # Protect decimal numbers
    protected = re.sub(r'(\d)\.(\d)', r'\1<DOT>\2', protected)

    # Protect ellipsis
    protected = protected.replace('...', '<ELLIPSIS>')

    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', protected)

    # Restore protected characters
    result = []
    for s in sentences:
        s = s.replace('<DOT>', '.')
        s = s.replace('<ELLIPSIS>', '...')
        s = s.strip()
        if s:
            result.append(s)

    return result
```

### 2.3 LLM-Assisted Merge

**File**: `zylch_memory/zylch_memory/llm_merge.py`

```python
"""LLM-assisted memory reconsolidation."""

import anthropic
from typing import Optional

MERGE_PROMPT = """Merge these memories into a single coherent blob:

EXISTING MEMORY:
{existing}

NEW INFORMATION:
{new}

Rules:
1. Preserve ALL facts from both memories
2. Resolve conflicts - new information wins for time-sensitive facts (titles, locations, status)
3. Keep the result concise and well-organized
4. Use natural language prose, not bullet points
5. Maximum 500 words

Output ONLY the merged memory text, nothing else."""

class LLMMergeService:
    """LLM-assisted memory merge for reconsolidation."""

    def __init__(self, api_key: str, model: str = None):  # model from env var
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def merge(self, existing: str, new: str) -> str:
        """Merge two memory contents using LLM.

        Args:
            existing: Current blob content
            new: New information to merge

        Returns:
            Merged content string
        """
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": MERGE_PROMPT.format(existing=existing, new=new)
            }]
        )
        return response.content[0].text.strip()
```

### 2.4 Blob Storage (Supabase)

**File**: `zylch_memory/zylch_memory/blob_storage.py`

```python
"""Blob storage with sentence-level embeddings for Supabase."""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import uuid

from .text_processing import split_sentences
from .embeddings import EmbeddingEngine

class BlobStorage:
    """Storage for entity blobs with sentence-level embeddings."""

    def __init__(self, supabase_client, embedding_engine: EmbeddingEngine):
        self.supabase = supabase_client
        self.embeddings = embedding_engine

    def store_blob(
        self,
        owner_id: str,
        namespace: str,
        content: str,
        event_description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Store new blob with sentence embeddings.

        Returns the created blob record.
        """
        blob_id = str(uuid.uuid4())

        # Generate blob-level embedding
        blob_embedding = self.embeddings.encode(content)

        # Split into sentences and embed each
        sentences = split_sentences(content)
        sentence_embeddings = self.embeddings.encode_batch(sentences)

        # Build events array
        events = []
        if event_description:
            events.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "description": event_description
            })

        # Insert blob
        blob_data = {
            "id": blob_id,
            "owner_id": owner_id,
            "namespace": namespace,
            "content": content,
            "embedding": blob_embedding.tolist(),
            "events": events
        }

        result = self.supabase.table("blobs").insert(blob_data).execute()

        # Insert sentences
        sentence_records = [
            {
                "blob_id": blob_id,
                "owner_id": owner_id,
                "sentence_text": sent,
                "embedding": emb.tolist()
            }
            for i, (sent, emb) in enumerate(zip(sentences, sentence_embeddings))
        ]

        if sentence_records:
            self.supabase.table("blob_sentences").insert(sentence_records).execute()

        return result.data[0]

    def update_blob(
        self,
        blob_id: str,
        owner_id: str,
        content: str,
        event_description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update blob content and regenerate sentence embeddings."""
        # Get existing blob to append event
        existing = self.supabase.table("blobs")\
            .select("events")\
            .eq("id", blob_id)\
            .eq("owner_id", owner_id)\
            .single()\
            .execute()

        events = existing.data.get("events", [])
        if event_description:
            events.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "description": event_description
            })

        # Generate new embeddings
        blob_embedding = self.embeddings.encode(content)
        sentences = split_sentences(content)
        sentence_embeddings = self.embeddings.encode_batch(sentences)

        # Update blob
        blob_data = {
            "content": content,
            "embedding": blob_embedding.tolist(),
            "events": events
        }

        result = self.supabase.table("blobs")\
            .update(blob_data)\
            .eq("id", blob_id)\
            .eq("owner_id", owner_id)\
            .execute()

        # Delete old sentences (CASCADE doesn't apply to updates)
        self.supabase.table("blob_sentences")\
            .delete()\
            .eq("blob_id", blob_id)\
            .execute()

        # Insert new sentences
        sentence_records = [
            {
                "blob_id": blob_id,
                "owner_id": owner_id,
                "sentence_text": sent,
                "embedding": emb.tolist()
            }
            for i, (sent, emb) in enumerate(zip(sentences, sentence_embeddings))
        ]

        if sentence_records:
            self.supabase.table("blob_sentences").insert(sentence_records).execute()

        return result.data[0]

    def get_blob(self, blob_id: str, owner_id: str) -> Optional[Dict[str, Any]]:
        """Get blob by ID."""
        result = self.supabase.table("blobs")\
            .select("*")\
            .eq("id", blob_id)\
            .eq("owner_id", owner_id)\
            .single()\
            .execute()
        return result.data if result.data else None

    def delete_blob(self, blob_id: str, owner_id: str) -> bool:
        """Delete blob (sentences cascade automatically)."""
        result = self.supabase.table("blobs")\
            .delete()\
            .eq("id", blob_id)\
            .eq("owner_id", owner_id)\
            .execute()
        return len(result.data) > 0

    def get_stats(self, owner_id: str) -> Dict[str, Any]:
        """Get memory statistics for owner."""
        blobs = self.supabase.table("blobs")\
            .select("id, namespace, content")\
            .eq("owner_id", owner_id)\
            .execute()

        sentences = self.supabase.table("blob_sentences")\
            .select("id", count="exact")\
            .eq("owner_id", owner_id)\
            .execute()

        namespaces = list(set(b["namespace"] for b in blobs.data))
        avg_sentences = sentences.count / len(blobs.data) if blobs.data else 0

        return {
            "total_blobs": len(blobs.data),
            "total_sentences": sentences.count,
            "namespaces": namespaces,
            "avg_blob_size": round(avg_sentences, 2)
        }
```

### 2.5 Hybrid Search Engine

**File**: `zylch_memory/zylch_memory/hybrid_search.py`

```python
"""Hybrid search combining FTS and semantic search."""

from dataclasses import dataclass
from typing import List, Optional
import numpy as np

from .embeddings import EmbeddingEngine

DEFAULT_FTS_WEIGHT = 0.5  # Configurable balance between FTS and semantic

@dataclass
class SearchResult:
    blob_id: str
    content: str
    namespace: str
    fts_score: float
    semantic_score: float
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

        # Generate query embedding
        query_embedding = self.embeddings.encode(query)

        # Call Supabase hybrid search function
        result = self.supabase.rpc(
            "hybrid_search_blobs",
            {
                "p_owner_id": owner_id,
                "p_query": query,
                "p_query_embedding": query_embedding.tolist(),
                "p_namespace": namespace,
                "p_fts_weight": fts_weight,
                "p_limit": limit
            }
        ).execute()

        # Get matching sentences for each result
        results = []
        for row in result.data:
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
        results = self.search(
            owner_id=owner_id,
            query=content,
            namespace=namespace,
            limit=1,
            alpha=0.5  # Balanced for reconsolidation
        )

        if results and results[0].hybrid_score >= self.RECONSOLIDATION_THRESHOLD:
            return results[0]
        return None

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
            emb = np.array(s["embedding"])
            sim = float(np.dot(query_embedding, emb) /
                       (np.linalg.norm(query_embedding) * np.linalg.norm(emb)))
            scored.append((sim, s["sentence_text"]))

        # Return top-k
        scored.sort(reverse=True)
        return [text for _, text in scored[:top_k]]
```

### 2.6 Configuration Updates

Add to `zylch_memory/zylch_memory/config.py`:

```python
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
    default=None,  # uses ANTHROPIC_MODEL env var
    description="Model for LLM merge (defaults to provider model from env)"
)
```

---

## Phase 3: API Endpoints

**Dependencies**: Phase 2 (core package must be functional)

### 3.1 Create Memory Router

**File**: `zylch/api/routes/memory.py`

```python
"""Memory API routes for entity-centric memory system."""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
import logging

from zylch.api.firebase_auth import get_current_user, get_user_id_from_token
from zylch.storage.supabase_client import SupabaseStorage
from zylch.config import settings

from zylch_memory import EmbeddingEngine
from zylch_memory.blob_storage import BlobStorage
from zylch_memory.hybrid_search import HybridSearchEngine
from zylch_memory.llm_merge import LLMMergeService

logger = logging.getLogger(__name__)
router = APIRouter()

# === Service instances (lazy-loaded) ===

_embedding_engine: Optional[EmbeddingEngine] = None
_blob_storage: Optional[BlobStorage] = None
_search_engine: Optional[HybridSearchEngine] = None
_llm_merge: Optional[LLMMergeService] = None

def get_supabase():
    return SupabaseStorage(
        url=settings.supabase_url,
        key=settings.supabase_service_role_key
    )

def get_embedding_engine() -> EmbeddingEngine:
    global _embedding_engine
    if _embedding_engine is None:
        _embedding_engine = EmbeddingEngine()
    return _embedding_engine

def get_blob_storage() -> BlobStorage:
    global _blob_storage
    if _blob_storage is None:
        _blob_storage = BlobStorage(get_supabase(), get_embedding_engine())
    return _blob_storage

def get_search_engine() -> HybridSearchEngine:
    global _search_engine
    if _search_engine is None:
        _search_engine = HybridSearchEngine(get_supabase(), get_embedding_engine())
    return _search_engine

def get_llm_merge() -> Optional[LLMMergeService]:
    global _llm_merge
    if _llm_merge is None and settings.anthropic_api_key:
        _llm_merge = LLMMergeService(api_key=settings.anthropic_api_key)
    return _llm_merge

# === Request/Response Models ===

class StoreMemoryRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000, description="Memory content")
    namespace: Optional[str] = Field(None, description="Namespace (auto-generated if not provided)")
    event_description: Optional[str] = Field(None, description="Event that triggered this memory")

class MemoryResponse(BaseModel):
    id: str
    namespace: str
    content: str
    events: List[dict]
    created_at: str
    updated_at: str

class SearchResultItem(BaseModel):
    id: str
    namespace: str
    content: str
    fts_score: float
    semantic_score: float
    hybrid_score: float
    matching_sentences: List[str]

class SearchResponse(BaseModel):
    results: List[SearchResultItem]
    total: int
    fts_weight: float

class StatsResponse(BaseModel):
    total_blobs: int
    total_sentences: int
    namespaces: List[str]
    avg_blob_size: float

# === Endpoints ===

@router.post("/store", response_model=MemoryResponse, status_code=201)
async def store_memory(
    request: StoreMemoryRequest,
    user: dict = Depends(get_current_user)
):
    """Store a memory blob with automatic reconsolidation.

    If similar content exists (hybrid_score > 0.65), it will be merged
    via LLM-assisted reconsolidation. Otherwise, a new blob is created.
    """
    user_id = get_user_id_from_token(user)
    namespace = request.namespace or f"user:{user_id}"

    storage = get_blob_storage()
    search = get_search_engine()
    llm = get_llm_merge()

    try:
        # Check for reconsolidation candidate
        existing = search.find_for_reconsolidation(
            owner_id=user_id,
            content=request.content,
            namespace=namespace
        )

        if existing and llm:
            # Reconsolidate: merge with LLM
            merged_content = llm.merge(existing.content, request.content)
            result = storage.update_blob(
                blob_id=existing.blob_id,
                owner_id=user_id,
                content=merged_content,
                event_description=request.event_description or "Reconsolidated with new information"
            )
        elif existing:
            # Reconsolidate without LLM: simple append
            merged_content = f"{existing.content}\n\n{request.content}"
            result = storage.update_blob(
                blob_id=existing.blob_id,
                owner_id=user_id,
                content=merged_content,
                event_description=request.event_description
            )
        else:
            # Create new blob
            result = storage.store_blob(
                owner_id=user_id,
                namespace=namespace,
                content=request.content,
                event_description=request.event_description
            )

        return MemoryResponse(
            id=result["id"],
            namespace=result["namespace"],
            content=result["content"],
            events=result.get("events", []),
            created_at=result["created_at"],
            updated_at=result["updated_at"]
        )

    except Exception as e:
        logger.error(f"Error storing memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search", response_model=SearchResponse)
async def search_memory(
    q: str = Query(..., min_length=1, description="Search query"),
    namespace: Optional[str] = Query(None, description="Filter by namespace"),
    limit: int = Query(10, ge=1, le=100),
    alpha: Optional[float] = Query(None, ge=0, le=1, description="FTS weight override"),
    user: dict = Depends(get_current_user)
):
    """Search memories using hybrid FTS + semantic search.

    Alpha controls the balance: 0=semantic only, 1=FTS only, 0.5=balanced (default).
    """
    user_id = get_user_id_from_token(user)
    search = get_search_engine()
    fts_weight = alpha if alpha is not None else 0.5

    try:
        results = search.search(
            owner_id=user_id,
            query=q,
            namespace=namespace,
            limit=limit,
            alpha=fts_weight
        )

        return SearchResponse(
            results=[
                SearchResultItem(
                    id=r.blob_id,
                    namespace=r.namespace,
                    content=r.content,
                    fts_score=r.fts_score,
                    semantic_score=r.semantic_score,
                    hybrid_score=r.hybrid_score,
                    matching_sentences=r.matching_sentences
                )
                for r in results
            ],
            total=len(results),
            fts_weight=fts_weight
        )

    except Exception as e:
        logger.error(f"Error searching memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{blob_id}", response_model=MemoryResponse)
async def get_memory(
    blob_id: str,
    user: dict = Depends(get_current_user)
):
    """Get a specific memory blob by ID."""
    user_id = get_user_id_from_token(user)
    storage = get_blob_storage()

    result = storage.get_blob(blob_id, user_id)
    if not result:
        raise HTTPException(status_code=404, detail="Memory not found")

    return MemoryResponse(
        id=result["id"],
        namespace=result["namespace"],
        content=result["content"],
        events=result.get("events", []),
        created_at=result["created_at"],
        updated_at=result["updated_at"]
    )


@router.put("/{blob_id}", response_model=MemoryResponse)
async def update_memory(
    blob_id: str,
    request: StoreMemoryRequest,
    user: dict = Depends(get_current_user)
):
    """Update a memory blob with new content.

    If LLM merge is enabled, new content is intelligently merged with existing.
    """
    user_id = get_user_id_from_token(user)
    storage = get_blob_storage()
    llm = get_llm_merge()

    existing = storage.get_blob(blob_id, user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Memory not found")

    try:
        if llm:
            merged_content = llm.merge(existing["content"], request.content)
        else:
            merged_content = request.content

        result = storage.update_blob(
            blob_id=blob_id,
            owner_id=user_id,
            content=merged_content,
            event_description=request.event_description
        )

        return MemoryResponse(
            id=result["id"],
            namespace=result["namespace"],
            content=result["content"],
            events=result.get("events", []),
            created_at=result["created_at"],
            updated_at=result["updated_at"]
        )

    except Exception as e:
        logger.error(f"Error updating memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{blob_id}", status_code=204)
async def delete_memory(
    blob_id: str,
    user: dict = Depends(get_current_user)
):
    """Delete a memory blob and its sentence embeddings."""
    user_id = get_user_id_from_token(user)
    storage = get_blob_storage()

    success = storage.delete_blob(blob_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")


@router.get("/", response_model=StatsResponse)
async def get_memory_stats(
    user: dict = Depends(get_current_user)
):
    """Get memory statistics for the current user."""
    user_id = get_user_id_from_token(user)
    storage = get_blob_storage()

    stats = storage.get_stats(user_id)
    return StatsResponse(**stats)
```

### 3.2 Register Router

Update `zylch/api/main.py`:

```python
from zylch.api.routes import memory

# Add router registration
app.include_router(memory.router, prefix="/api/memory", tags=["memory"])
```

---

## Phase 4: Integration Points

**Dependencies**: Phase 3 (API must be functional)

### 4.1 Update Memory Worker

Update `zylch/workers/memory_worker.py` to use new blob system:

```python
from zylch_memory.blob_storage import BlobStorage
from zylch_memory.hybrid_search import HybridSearchEngine

def store_relationship_context(
    self,
    owner_id: str,
    contact_email: str,
    context: str,
    source_email_id: str
):
    """Store relationship context using blob system."""
    namespace = f"user:{owner_id}"
    content = f"Relationship with {contact_email}: {context}"

    self.blob_storage.store_blob(
        owner_id=owner_id,
        namespace=namespace,
        content=content,
        event_description=f"Extracted from email {source_email_id}"
    )
```

### 4.2 Update Tools Factory

Update `zylch/tools/factory.py` to use hybrid search:

```python
class _SearchLocalMemoryTool(BaseTool):
    """Search memory using hybrid FTS + semantic search."""

    def execute(self, query: str, namespace: Optional[str] = None) -> str:
        results = self.search_engine.search(
            owner_id=self.owner_id,
            query=query,
            namespace=namespace,
            limit=5
        )

        if not results:
            return "No memories found."

        output = [f"Found {len(results)} memories:"]
        for r in results:
            output.append(f"\n**{r.namespace}** (score: {r.hybrid_score:.2f})")
            output.append(r.content[:200] + "..." if len(r.content) > 200 else r.content)

        return "\n".join(output)
```

---

## Phase 5: Testing Strategy

**Dependencies**: Phase 4 (all components implemented)

### 5.1 Unit Tests

| File | Tests |
|------|-------|
| `tests/test_text_processing.py` | Sentence splitter edge cases |
| `tests/test_hybrid_search.py` | Score combination, normalization |
| `tests/test_llm_merge.py` | Merge prompt handling (mocked) |

### 5.2 Integration Tests

| File | Tests |
|------|-------|
| `tests/test_blob_storage.py` | CRUD operations, sentence embedding |
| `tests/test_reconsolidation.py` | Full reconsolidation flow |
| `tests/api/test_memory_api.py` | All API endpoints |

### 5.3 Performance Benchmarks

- Hybrid search latency: < 200ms for 10K blobs
- Reconsolidation detection: > 90% precision

---

## Success Criteria

### Functional
- [ ] Hybrid search returns results combining FTS and semantic scores
- [ ] Reconsolidation correctly identifies and merges duplicates
- [ ] LLM merge produces coherent, non-redundant content
- [ ] All API endpoints return correct responses with auth

### Non-Functional
- [ ] API response times < 500ms for all endpoints
- [ ] Backward compatibility with existing memory calls
- [ ] No regression in existing tests
- [ ] Memory usage reasonable for 10K+ blobs

### Integration
- [ ] Memory worker uses new blob system
- [ ] Tools factory integrates hybrid search
- [ ] Dashboard can call memory API

---

## API Endpoints Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/memory/store` | Store blob (with auto-reconsolidation) |
| GET | `/api/memory/search?q=...` | Hybrid search |
| GET | `/api/memory/{blob_id}` | Get specific blob |
| PUT | `/api/memory/{blob_id}` | Update blob (with LLM merge) |
| DELETE | `/api/memory/{blob_id}` | Delete blob |
| GET | `/api/memory/` | Get statistics |

---

## File Summary

### New Files to Create

| File | Purpose |
|------|---------|
| `zylch/storage/migrations/004_entity_memory_blobs.sql` | Database schema |
| `zylch_memory/zylch_memory/text_processing.py` | Sentence splitter |
| `zylch_memory/zylch_memory/hybrid_search.py` | Hybrid search engine |
| `zylch_memory/zylch_memory/llm_merge.py` | LLM-assisted merge |
| `zylch_memory/zylch_memory/blob_storage.py` | Blob CRUD |
| `zylch/api/routes/memory.py` | API endpoints |

### Files to Modify

| File | Changes |
|------|---------|
| `zylch_memory/zylch_memory/config.py` | Add hybrid search config |
| `zylch/api/main.py` | Register memory router |
| `zylch/workers/memory_worker.py` | Use blob storage |
| `zylch/tools/factory.py` | Use hybrid search |

---

*Plan created: December 2025*
*Branch: entities*
