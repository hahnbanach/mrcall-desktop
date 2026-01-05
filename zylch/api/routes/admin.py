"""Admin routes for cache and memory management."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
import os
import shutil
from pathlib import Path

from zylch.config import settings

router = APIRouter()


class ClearResponse(BaseModel):
    """Response for clear operations."""
    success: bool
    message: str
    details: Dict[str, Any]


@router.post("/memory/clear", response_model=ClearResponse)
async def clear_memory(confirm: bool = False):
    """Clear all behavioral corrections from memory database.

    Query Parameters:
        confirm: Must be True to execute (safety check)

    Returns:
        Success status and details about what was cleared
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Must set confirm=true to clear memory. This action cannot be undone."
        )

    try:
        # Path to memory database
        cache_path = Path(settings.cache_dir)
        memory_db = cache_path / "memory.db"
        indices_dir = cache_path / "indices"

        deleted_files = []

        # Remove memory database
        if memory_db.exists():
            db_size = memory_db.stat().st_size
            memory_db.unlink()
            deleted_files.append({
                "file": str(memory_db),
                "size_bytes": db_size
            })

        # Remove indices directory
        if indices_dir.exists():
            # Calculate size before deletion
            indices_size = sum(f.stat().st_size for f in indices_dir.rglob('*') if f.is_file())
            shutil.rmtree(indices_dir)
            deleted_files.append({
                "directory": str(indices_dir),
                "size_bytes": indices_size
            })

        total_bytes = sum(item.get("size_bytes", 0) for item in deleted_files)

        return ClearResponse(
            success=True,
            message="Memory database cleared successfully",
            details={
                "deleted": deleted_files,
                "total_bytes_freed": total_bytes,
                "total_mb_freed": round(total_bytes / (1024 * 1024), 2)
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error clearing memory: {str(e)}")


@router.post("/cache/clear", response_model=ClearResponse)
async def clear_cache(confirm: bool = False):
    """Clear entire cache directory (all caches including memory).

    Query Parameters:
        confirm: Must be True to execute (safety check)

    Returns:
        Success status and details about what was cleared
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Must set confirm=true to clear cache. This action cannot be undone."
        )

    try:
        cache_path = Path(settings.cache_dir)

        if not cache_path.exists():
            return ClearResponse(
                success=True,
                message="Cache directory not found (already empty)",
                details={
                    "deleted": [],
                    "total_bytes_freed": 0,
                    "total_mb_freed": 0
                }
            )

        # Calculate total size before deletion
        total_size = sum(f.stat().st_size for f in cache_path.rglob('*') if f.is_file())

        deleted_items = []

        # Remove all contents except .gitkeep
        for item in cache_path.iterdir():
            if item.name == '.gitkeep':
                continue

            if item.is_file():
                size = item.stat().st_size
                item.unlink()
                deleted_items.append({
                    "type": "file",
                    "path": str(item),
                    "size_bytes": size
                })
            elif item.is_dir():
                # Calculate directory size
                dir_size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file())
                shutil.rmtree(item)
                deleted_items.append({
                    "type": "directory",
                    "path": str(item),
                    "size_bytes": dir_size
                })

        return ClearResponse(
            success=True,
            message="Cache cleared successfully",
            details={
                "deleted": deleted_items,
                "total_bytes_freed": total_size,
                "total_mb_freed": round(total_size / (1024 * 1024), 2),
                "cache_location": str(cache_path)
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error clearing cache: {str(e)}")


@router.get("/cache/info")
async def cache_info():
    """Get information about cache directory contents.

    Returns:
        Cache directory statistics and contents
    """
    try:
        cache_path = Path(settings.cache_dir)

        if not cache_path.exists():
            return {
                "exists": False,
                "path": str(cache_path),
                "total_size_bytes": 0,
                "total_size_mb": 0,
                "contents": []
            }

        contents = []
        total_size = 0

        for item in cache_path.iterdir():
            if item.is_file():
                size = item.stat().st_size
                total_size += size
                contents.append({
                    "type": "file",
                    "name": item.name,
                    "size_bytes": size,
                    "size_mb": round(size / (1024 * 1024), 2)
                })
            elif item.is_dir():
                dir_size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file())
                file_count = sum(1 for _ in item.rglob('*') if _.is_file())
                total_size += dir_size
                contents.append({
                    "type": "directory",
                    "name": item.name,
                    "size_bytes": dir_size,
                    "size_mb": round(dir_size / (1024 * 1024), 2),
                    "file_count": file_count
                })

        return {
            "exists": True,
            "path": str(cache_path),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "contents": contents
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading cache info: {str(e)}")
