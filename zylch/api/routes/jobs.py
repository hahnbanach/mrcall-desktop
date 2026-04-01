"""Background job management API.

Provides endpoints for starting, monitoring, and cancelling long-running
background jobs (memory processing, task detection, sync).

Jobs run in a thread pool to avoid blocking the FastAPI event loop.
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from zylch.api.firebase_auth import get_current_user, get_user_id_from_token, get_user_email_from_token
from zylch.storage import Storage

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class StartJobRequest(BaseModel):
    """Request model for starting a background job."""
    job_type: str  # 'memory_process', 'task_process', 'sync'
    channel: Optional[str] = "all"  # 'email', 'calendar', 'all'


class JobStatusResponse(BaseModel):
    """Response model for job status."""
    id: str
    job_type: str
    channel: Optional[str]
    status: str  # pending, running, completed, failed, cancelled
    progress_pct: int
    items_processed: int
    total_items: Optional[int]
    status_message: Optional[str]
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    last_error: Optional[str]
    result: Optional[dict]


class CancelJobResponse(BaseModel):
    """Response model for job cancellation."""
    cancelled: bool


# =============================================================================
# Dependency Injection
# =============================================================================

# Shared Supabase storage instance
_storage: Optional[Storage] = None


def get_storage() -> Storage:
    """Get shared Supabase storage instance."""
    global _storage
    if _storage is None:
        _storage = Storage.get_instance()
    return _storage


def get_anthropic_key(user: dict = Depends(get_current_user)) -> str:
    """Get user's Anthropic API key from Supabase.

    Args:
        user: Decoded Firebase token

    Returns:
        User's Anthropic API key

    Raises:
        HTTPException: If Anthropic not connected
    """
    owner_id = get_user_id_from_token(user)
    storage = get_storage()

    # Get Anthropic credentials (BYOK)
    creds = storage.get_provider_credentials(owner_id, 'anthropic')
    if not creds or not creds.get('api_key'):
        raise HTTPException(
            status_code=400,
            detail="Anthropic not connected. Use /connect anthropic to configure your API key."
        )

    return creds['api_key']


# =============================================================================
# Routes
# =============================================================================

@router.post("/start", response_model=JobStatusResponse)
async def start_job(
    request: StartJobRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user)
):
    """Start a background job. Returns immediately with job_id.

    If a duplicate job exists (same user, type, channel, pending/running),
    returns the existing job instead of creating a new one.

    Args:
        request: Job parameters (job_type, channel)
        background_tasks: FastAPI background tasks
        user: Authenticated user

    Returns:
        Job status (new or existing)
    """
    owner_id = get_user_id_from_token(user)
    user_email = get_user_email_from_token(user)
    storage = get_storage()

    # Validate job_type
    valid_types = ["memory_process", "task_process", "sync"]
    if request.job_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid job_type: {request.job_type}. Must be one of: {valid_types}"
        )

    # Validate channel
    valid_channels = ["email", "calendar", "all", None]
    if request.channel not in valid_channels:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid channel: {request.channel}. Must be one of: {valid_channels}"
        )

    # Create job (returns existing if duplicate)
    job = storage.create_background_job(
        owner_id=owner_id,
        job_type=request.job_type,
        channel=request.channel
    )

    logger.info(f"Job request: {request.job_type}/{request.channel} for user {owner_id} -> {job['status']}")

    # If it's a new job (pending), schedule execution
    if job["status"] == "pending":
        # Get Anthropic key (required for memory/task processing)
        if request.job_type in ["memory_process", "task_process"]:
            try:
                anthropic_key = get_anthropic_key(user)
            except HTTPException:
                # Clean up the pending job
                storage.cancel_background_job(job["id"], owner_id)
                raise
        else:
            anthropic_key = ""

        # Import here to avoid circular imports
        from zylch.services.job_executor import JobExecutor

        executor = JobExecutor(storage)

        # Schedule execution in background
        background_tasks.add_task(
            executor.execute_job,
            job["id"],
            owner_id,
            anthropic_key,
            user_email
        )

        logger.info(f"Scheduled background job {job['id']}")

    return _job_to_response(job)


# NOTE: /active MUST be defined BEFORE /{job_id} — otherwise FastAPI
# matches the literal "active" as a job_id path parameter.
@router.get("/active")
async def get_active_job(
    business_id: str,
    user: dict = Depends(get_current_user)
):
    """Get any active (pending/running) job for a business_id.

    This is the single endpoint frontends poll to determine if the chat
    should be blocked. Job-type agnostic — any job (training, configure,
    reset, etc.) that has a business_id will be returned.

    Args:
        business_id: MrCall business ID (query param)
        user: Authenticated user

    Returns:
        {active: true, job_id, job_type, status, progress_pct, status_message, created_at}
        or {active: false} if no active job
    """
    owner_id = get_user_id_from_token(user)
    storage = get_storage()

    logger.debug(f"[jobs/active] Checking active jobs for business_id={business_id}, owner_id={owner_id}")
    job = storage.get_active_job_for_business(owner_id, business_id)

    if not job:
        return {"active": False}

    return {
        "active": True,
        "job_id": str(job["id"]),
        "job_type": job.get("job_type"),
        "status": job.get("status"),
        "progress_pct": job.get("progress_pct", 0),
        "status_message": job.get("status_message"),
        "created_at": str(job.get("created_at", "")),
    }


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    user: dict = Depends(get_current_user)
):
    """Get job status. Poll this every 5 seconds for progress updates.

    Args:
        job_id: Job UUID
        user: Authenticated user

    Returns:
        Current job status
    """
    owner_id = get_user_id_from_token(user)
    storage = get_storage()

    job = storage.get_background_job(job_id, owner_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return _job_to_response(job)


@router.get("/", response_model=List[JobStatusResponse])
async def list_jobs(
    status: Optional[str] = None,
    limit: int = 20,
    user: dict = Depends(get_current_user)
):
    """List user's background jobs, most recent first.

    Args:
        status: Optional filter by status
        limit: Maximum number of jobs to return (default: 20)
        user: Authenticated user

    Returns:
        List of job statuses
    """
    owner_id = get_user_id_from_token(user)
    storage = get_storage()

    # Validate status filter
    if status:
        valid_statuses = ["pending", "running", "completed", "failed", "cancelled"]
        if status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status}. Must be one of: {valid_statuses}"
            )

    jobs = storage.get_user_background_jobs(owner_id, status=status, limit=limit)
    return [_job_to_response(j) for j in jobs]


@router.post("/{job_id}/stop", response_model=CancelJobResponse)
async def stop_job(
    job_id: str,
    user: dict = Depends(get_current_user)
):
    """Stop a running job by setting it to cancelled.

    The worker thread detects the status change via _should_stop_job()
    and exits gracefully at the next checkpoint.

    Unlike cancel (which only works on pending jobs), stop works on
    running jobs.

    Args:
        job_id: Job UUID
        user: Authenticated user

    Returns:
        {cancelled: true} if stop succeeded
    """
    owner_id = get_user_id_from_token(user)
    storage = get_storage()

    logger.debug(f"[jobs/stop] Attempting to stop job {job_id} for owner {owner_id}")

    killed = storage.kill_background_job(job_id, owner_id)
    logger.debug(f"[jobs/stop] kill_background_job(job_id={job_id}, owner_id={owner_id}) -> {killed}")

    if not killed:
        job = storage.get_background_job(job_id, owner_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        raise HTTPException(
            status_code=400,
            detail=f"Cannot stop job with status '{job['status']}'. Only running jobs can be stopped."
        )

    logger.info(f"[jobs/stop] Stopped running job {job_id}")
    return CancelJobResponse(cancelled=True)


@router.post("/{job_id}/cancel", response_model=CancelJobResponse)
async def cancel_job(
    job_id: str,
    user: dict = Depends(get_current_user)
):
    """Cancel a pending job. Running jobs cannot be cancelled (use stop instead).

    Args:
        job_id: Job UUID
        user: Authenticated user

    Returns:
        Cancellation result
    """
    owner_id = get_user_id_from_token(user)
    storage = get_storage()

    cancelled = storage.cancel_background_job(job_id, owner_id)

    if not cancelled:
        # Check if job exists
        job = storage.get_background_job(job_id, owner_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel job with status '{job['status']}'. Only pending jobs can be cancelled."
            )

    logger.info(f"Cancelled job {job_id}")
    return CancelJobResponse(cancelled=True)


# =============================================================================
# Helpers
# =============================================================================

def _job_to_response(job: dict) -> JobStatusResponse:
    """Convert job dict to response model.

    Args:
        job: Job record from database

    Returns:
        JobStatusResponse model
    """
    return JobStatusResponse(
        id=str(job.get("id", "")),
        job_type=job.get("job_type", ""),
        channel=job.get("channel"),
        status=job.get("status", "pending"),
        progress_pct=job.get("progress_pct", 0),
        items_processed=job.get("items_processed", 0),
        total_items=job.get("total_items"),
        status_message=job.get("status_message"),
        created_at=str(job.get("created_at", "")),
        started_at=str(job.get("started_at", "")) if job.get("started_at") else None,
        completed_at=str(job.get("completed_at", "")) if job.get("completed_at") else None,
        last_error=job.get("last_error"),
        result=job.get("result")
    )
