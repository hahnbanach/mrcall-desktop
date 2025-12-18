"""Memory API routes for entity-centric memory system."""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
import logging

from zylch.api.firebase_auth import get_current_user, get_user_id_from_token
from zylch.storage.supabase_client import SupabaseStorage
from zylch.config import settings

from zylch_memory import EmbeddingEngine
from zylch_memory.config import ZylchMemoryConfig
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
    return SupabaseStorage.get_instance().client

def get_embedding_engine() -> EmbeddingEngine:
    global _embedding_engine
    if _embedding_engine is None:
        config = ZylchMemoryConfig()
        _embedding_engine = EmbeddingEngine(config)
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

def get_llm_merge(user_id: str) -> Optional[LLMMergeService]:
    """Get LLM merge service using user's Anthropic API key."""
    global _llm_merge
    try:
        storage = SupabaseStorage.get_instance()
        api_key = storage.get_anthropic_key(user_id)
        if api_key:
            return LLMMergeService(api_key=api_key)
    except Exception as e:
        logger.warning(f"Could not initialize LLM merge service: {e}")
    return None

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
    llm = get_llm_merge(user_id)

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
    llm = get_llm_merge(user_id)

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
