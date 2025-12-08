#!/usr/bin/env python3
"""Run avatar compute worker locally.

This processes the avatar_compute_queue and generates avatars.
In production, this runs as a Railway cron job every 5 minutes.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from zylch.config import settings
from zylch.storage.supabase_client import SupabaseStorage
from zylch.workers.avatar_compute_worker import AvatarComputeWorker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def main():
    """Run avatar worker once."""
    logger.info("Starting avatar compute worker...")

    # Initialize storage
    storage = SupabaseStorage()

    # Create worker (no shared anthropic client - uses per-user keys)
    worker = AvatarComputeWorker(
        storage=storage,
        anthropic_client=None,  # Not used - creates per-user clients
        batch_size=10
    )

    # Run once
    await worker.run_once()

    logger.info("Avatar worker complete")


if __name__ == '__main__':
    asyncio.run(main())
