#!/usr/bin/env python3
"""Test script to debug hybrid search and reconsolidation.

Usage:
    python scripts/test_hybrid_search.py "Acme Corp contact@example.com"
    python scripts/test_hybrid_search.py --query "your search query"
    python scripts/test_hybrid_search.py --blob-id UUID  # search with content of existing blob
"""

import argparse
import json
import os
import sys

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from zylch_memory import EmbeddingEngine, ZylchMemoryConfig


def get_supabase_client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        sys.exit(1)
    return create_client(url, key)


def search_blobs(client, owner_id: str, query: str, namespace: str = None, limit: int = 10):
    """Execute hybrid search and return results with scores."""
    config = ZylchMemoryConfig()
    embedding_engine = EmbeddingEngine(config)

    # Generate query embedding
    query_embedding = embedding_engine.encode(query)

    # Call hybrid search
    result = client.rpc(
        "hybrid_search_blobs",
        {
            "p_owner_id": owner_id,
            "p_query": query,
            "p_query_embedding": query_embedding.tolist(),
            "p_namespace": namespace,
            "p_fts_weight": 0.5,
            "p_limit": limit
        }
    ).execute()

    return result.data or []


def get_blob_by_id(client, blob_id: str):
    """Get a blob by ID."""
    result = client.table("blobs").select("*").eq("id", blob_id).execute()
    if result.data:
        return result.data[0]
    return None


def list_blobs(client, owner_id: str, limit: int = 20):
    """List recent blobs for an owner."""
    result = client.table("blobs")\
        .select("id, content, created_at")\
        .eq("owner_id", owner_id)\
        .order("created_at", desc=True)\
        .limit(limit)\
        .execute()
    return result.data or []


def main():
    parser = argparse.ArgumentParser(description="Test hybrid search for reconsolidation debugging")
    parser.add_argument("query", nargs="?", help="Search query (text)")
    parser.add_argument("--blob-id", help="Use content of existing blob as query")
    parser.add_argument("--owner-id", help="Owner ID (Firebase UID)", required=True)
    parser.add_argument("--namespace", help="Namespace filter (default: user:{owner_id})")
    parser.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    parser.add_argument("--list", action="store_true", help="List recent blobs instead of searching")

    args = parser.parse_args()

    client = get_supabase_client()
    namespace = args.namespace or f"user:{args.owner_id}"

    # List mode
    if args.list:
        print(f"\n=== Recent blobs for owner {args.owner_id} ===\n")
        blobs = list_blobs(client, args.owner_id, args.limit)
        for i, blob in enumerate(blobs, 1):
            content_preview = blob["content"][:150].replace("\n", " ")
            print(f"{i}. {blob['id']}")
            print(f"   {content_preview}...")
            print()
        return

    # Get query
    if args.blob_id:
        blob = get_blob_by_id(client, args.blob_id)
        if not blob:
            print(f"Error: Blob {args.blob_id} not found")
            sys.exit(1)
        query = blob["content"]
        print(f"\n=== Using blob {args.blob_id} as query ===")
        print(f"Content preview: {query[:200]}...")
    elif args.query:
        query = args.query
    else:
        print("Error: Provide a query or --blob-id")
        sys.exit(1)

    print(f"\n=== Hybrid Search Results ===")
    print(f"Query (first 100 chars): {query[:100]}...")
    print(f"Namespace: {namespace}")
    print(f"Reconsolidation threshold: 0.65")
    print()

    results = search_blobs(client, args.owner_id, query, namespace, args.limit)

    if not results:
        print("No results found.")
        return

    print(f"Found {len(results)} results:\n")

    for i, row in enumerate(results, 1):
        hybrid = row["hybrid_score"]
        fts = row["fts_score"]
        semantic = row["semantic_score"]

        # Would this reconsolidate?
        match = "✅ MATCH" if hybrid >= 0.65 else "❌ NO MATCH"

        content_preview = row["content"][:150].replace("\n", " ")

        print(f"{i}. {match} (hybrid={hybrid:.3f}, fts={fts:.3f}, semantic={semantic:.3f})")
        print(f"   blob_id: {row['blob_id']}")
        print(f"   content: {content_preview}...")
        print()


if __name__ == "__main__":
    main()
