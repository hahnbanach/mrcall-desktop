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
        sentence_embeddings = self.embeddings.encode(sentences) if sentences else []

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
        sentence_records = []
        for i, sent in enumerate(sentences):
            emb = sentence_embeddings[i] if len(sentence_embeddings) > i else self.embeddings.encode(sent)
            sentence_records.append({
                "blob_id": blob_id,
                "owner_id": owner_id,
                "sentence_text": sent,
                "embedding": emb.tolist() if hasattr(emb, 'tolist') else list(emb)
            })

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

        events = existing.data.get("events", []) if existing.data else []
        if event_description:
            events.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "description": event_description
            })

        # Generate new embeddings
        blob_embedding = self.embeddings.encode(content)
        sentences = split_sentences(content)
        sentence_embeddings = self.embeddings.encode(sentences) if sentences else []

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
        sentence_records = []
        for i, sent in enumerate(sentences):
            emb = sentence_embeddings[i] if len(sentence_embeddings) > i else self.embeddings.encode(sent)
            sentence_records.append({
                "blob_id": blob_id,
                "owner_id": owner_id,
                "sentence_text": sent,
                "embedding": emb.tolist() if hasattr(emb, 'tolist') else list(emb)
            })

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

        namespaces = list(set(b["namespace"] for b in blobs.data)) if blobs.data else []
        sentence_count = sentences.count if hasattr(sentences, 'count') else len(sentences.data) if sentences.data else 0
        avg_sentences = sentence_count / len(blobs.data) if blobs.data else 0

        return {
            "total_blobs": len(blobs.data) if blobs.data else 0,
            "total_sentences": sentence_count,
            "namespaces": namespaces,
            "avg_blob_size": round(avg_sentences, 2)
        }
