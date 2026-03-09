"""MrCall training management API.

Provides endpoints for checking training status and triggering
selective agent retraining based on variable change detection.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel

from zylch.api.firebase_auth import get_current_user, get_user_id_from_token, get_user_email_from_token
from zylch.storage.supabase_client import SupabaseStorage
from zylch.storage.database import get_session
from zylch.storage.models import BackgroundJob

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class ChangedVariable(BaseModel):
    name: str
    feature: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None


class TrainingStatusResponse(BaseModel):
    status: str  # untrained, current, stale, in_progress, unknown
    business_id: Optional[str] = None
    checked_at: Optional[str] = None
    snapshot_at: Optional[str] = None
    job_id: Optional[str] = None
    job_progress_pct: Optional[int] = None
    changed_variables: List[ChangedVariable] = []
    stale_features: List[str] = []
    current_features: List[str] = []
    all_features: List[str] = []
    error: Optional[str] = None


class StartTrainingRequest(BaseModel):
    force: bool = False
    features: Optional[List[str]] = None


class StartTrainingResponse(BaseModel):
    job_id: Optional[str] = None
    status: str
    features_to_train: List[str] = []
    message: str


# =============================================================================
# Dependency Injection
# =============================================================================

_storage: Optional[SupabaseStorage] = None


def get_storage() -> SupabaseStorage:
    global _storage
    if _storage is None:
        _storage = SupabaseStorage.get_instance()
    return _storage


def _get_llm_credentials(owner_id: str, storage: SupabaseStorage):
    """Get the user's LLM provider credentials.

    Tries anthropic, openai, mistral in order.

    Returns:
        Tuple of (api_key, provider) or raises HTTPException
    """
    for provider in ('anthropic', 'openai', 'mistral'):
        creds = storage.get_provider_credentials(owner_id, provider)
        if creds and creds.get('api_key'):
            return creds['api_key'], provider

    raise HTTPException(
        status_code=400,
        detail="No LLM provider connected. Connect one via /connect anthropic, /connect openai, or /connect mistral."
    )


# =============================================================================
# Routes
# =============================================================================

@router.get("/training/status", response_model=TrainingStatusResponse)
async def get_training_status(
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Get MrCall training status for the linked assistant.

    Compares current StarChat variable values against the trained snapshot
    to determine if retraining is needed.

    Returns status: untrained, current, stale, in_progress, or unknown.
    """
    from zylch.agents.trainers import MrCallConfiguratorTrainer
    from zylch.tools.starchat import StarChatClient
    from zylch.config import settings

    owner_id = get_user_id_from_token(user)
    storage = get_storage()

    all_features = list(MrCallConfiguratorTrainer.FEATURES.keys())

    # Check MrCall is linked
    business_id = storage.get_mrcall_link(owner_id)
    if not business_id:
        raise HTTPException(status_code=400, detail="No MrCall assistant linked.")

    # Check for in-progress training job
    try:
        with get_session() as session:
            job_rows = session.query(BackgroundJob).filter(
                BackgroundJob.owner_id == owner_id,
                BackgroundJob.job_type == 'mrcall_train',
                BackgroundJob.status.in_(['pending', 'running']),
            ).all()
            existing_jobs_data = [j.to_dict() for j in job_rows]

        if existing_jobs_data:
            job = existing_jobs_data[0]
            started_at = job.get('started_at')

            # Self-heal stuck jobs (> 10 minutes)
            if started_at and job['status'] == 'running':
                started_dt = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                if (datetime.now(timezone.utc) - started_dt).total_seconds() > 600:
                    logger.warning(f"[training/status] Self-healing stuck job {job['id']}")
                    storage.fail_background_job(job['id'], "Training timed out (self-healed)")
                else:
                    return TrainingStatusResponse(
                        status="in_progress",
                        business_id=business_id,
                        checked_at=datetime.now(timezone.utc).isoformat(),
                        job_id=job['id'],
                        job_progress_pct=job.get('progress_pct', 0),
                        all_features=all_features,
                    )
    except Exception as e:
        logger.warning(f"[training/status] Error checking jobs: {e}")

    # Load snapshot
    snapshot = storage.get_training_snapshot(owner_id, business_id)
    if snapshot is None:
        return TrainingStatusResponse(
            status="untrained",
            business_id=business_id,
            checked_at=datetime.now(timezone.utc).isoformat(),
            all_features=all_features,
        )

    # Fetch live variables from StarChat
    try:
        authorization = request.headers.get("authorization", "")
        firebase_token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization

        starchat = StarChatClient(
            base_url=settings.mrcall_base_url.rstrip('/'),
            auth_type="firebase",
            jwt_token=firebase_token,
            realm=settings.mrcall_realm,
            owner_id=owner_id,
        )

        business = await starchat.get_business_config(business_id)
        if not business:
            return TrainingStatusResponse(
                status="unknown",
                business_id=business_id,
                checked_at=datetime.now(timezone.utc).isoformat(),
                snapshot_at=snapshot.get('updated_at'),
                error="Business not found on StarChat",
                all_features=all_features,
            )

        live_variables = business.get("variables", {})

    except Exception as e:
        logger.warning(f"[training/status] Failed to fetch live variables: {e}")
        return TrainingStatusResponse(
            status="unknown",
            business_id=business_id,
            checked_at=datetime.now(timezone.utc).isoformat(),
            snapshot_at=snapshot.get('updated_at'),
            error=f"Could not reach StarChat API: {e}",
            all_features=all_features,
        )

    # Diff snapshot vs live
    snapshot_variables = snapshot.get('variables', {})
    logger.debug(f"[training/status] Snapshot has {len(snapshot_variables)} variables, live has {len(live_variables)} variables")
    diff = MrCallConfiguratorTrainer.diff_snapshot(snapshot_variables, live_variables)
    logger.debug(
        f"[training/status] Diff result: {len(diff['changed_variables'])} changed variables, "
        f"stale_features={diff['stale_features']}, current_features={diff['current_features']}"
    )
    for cv in diff["changed_variables"]:
        logger.debug(
            f"[training/status] Changed: {cv['name']} (feature={cv['feature']}) "
            f"old={cv['old_value']!r} -> new={cv['new_value']!r}"
        )

    changed_vars = [
        ChangedVariable(
            name=cv["name"],
            feature=cv["feature"],
            old_value=cv["old_value"],
            new_value=cv["new_value"],
        )
        for cv in diff["changed_variables"]
    ]

    if diff["stale_features"]:
        return TrainingStatusResponse(
            status="stale",
            business_id=business_id,
            checked_at=datetime.now(timezone.utc).isoformat(),
            snapshot_at=snapshot.get('updated_at'),
            changed_variables=changed_vars,
            stale_features=sorted(diff["stale_features"]),
            current_features=sorted(diff["current_features"]),
            all_features=all_features,
        )
    else:
        return TrainingStatusResponse(
            status="current",
            business_id=business_id,
            checked_at=datetime.now(timezone.utc).isoformat(),
            snapshot_at=snapshot.get('updated_at'),
            current_features=sorted(diff["current_features"]),
            all_features=all_features,
        )


@router.post("/training/start", response_model=StartTrainingResponse)
async def start_training(
    body: StartTrainingRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """Start MrCall agent training as a background job.

    Supports selective retraining (only features with changed variables)
    or force retraining all features.
    """
    from zylch.agents.trainers import MrCallConfiguratorTrainer

    owner_id = get_user_id_from_token(user)
    user_email = get_user_email_from_token(user)
    storage = get_storage()

    # Check MrCall is linked
    business_id = storage.get_mrcall_link(owner_id)
    if not business_id:
        raise HTTPException(status_code=400, detail="No MrCall assistant linked.")

    # Get LLM credentials
    api_key, llm_provider = _get_llm_credentials(owner_id, storage)

    # Check for existing running job
    try:
        with get_session() as session:
            job_rows = session.query(BackgroundJob).filter(
                BackgroundJob.owner_id == owner_id,
                BackgroundJob.job_type == 'mrcall_train',
                BackgroundJob.status.in_(['pending', 'running']),
            ).all()
            existing_jobs_data = [j.to_dict() for j in job_rows]

        if existing_jobs_data:
            raise HTTPException(
                status_code=409,
                detail=f"Training already in progress (job {existing_jobs_data[0]['id']})"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[training/start] Error checking existing jobs: {e}")

    # Validate features if specified
    if body.features:
        for feat in body.features:
            if feat not in MrCallConfiguratorTrainer.FEATURES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown feature: {feat}. Available: {list(MrCallConfiguratorTrainer.FEATURES.keys())}"
                )

    # Create background job
    job = storage.create_background_job(
        owner_id=owner_id,
        job_type='mrcall_train',
        channel='mrcall',
        params={
            "force": body.force,
            "features": body.features,
            "business_id": business_id,
        }
    )
    job_id = job['id']

    # Extract firebase token for StarChat auth
    authorization = request.headers.get("authorization", "")
    firebase_token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization

    # Determine features to train (for the response message)
    features_to_train = body.features or list(MrCallConfiguratorTrainer.FEATURES.keys())
    message = f"Training {len(features_to_train)} features"

    if not body.force and not body.features:
        message = "Training changed features (selective)"

    # Schedule background execution
    async def _run_training():
        try:
            # Claim the job
            claimed = storage.claim_background_job(job_id)
            if not claimed:
                logger.warning(f"[training/start] Could not claim job {job_id}")
                return

            from zylch.services.command_handlers import _handle_mrcall_agent_train

            context = {
                "source": "dashboard",
                "firebase_token": firebase_token,
            }

            # Determine feature / force from params
            feature = body.features[0] if body.features and len(body.features) == 1 else None
            force = body.force

            # Update progress
            storage.update_background_job_progress(
                job_id, progress_pct=10, items_processed=0,
                total_items=len(features_to_train),
                status_message="Starting training..."
            )

            result_msg = await _handle_mrcall_agent_train(
                storage, owner_id, api_key, llm_provider, user_email,
                feature=feature, context=context, force=force,
            )

            # Complete the job
            storage.complete_background_job(job_id, result={
                "message": result_msg,
                "features_trained": features_to_train,
            })
            logger.info(f"[training/start] Job {job_id} completed successfully")

        except Exception as e:
            logger.error(f"[training/start] Job {job_id} failed: {e}", exc_info=True)
            storage.fail_background_job(job_id, str(e))

    background_tasks.add_task(_run_training)

    return StartTrainingResponse(
        job_id=job_id,
        status="in_progress",
        features_to_train=features_to_train,
        message=message,
    )


class ResetVariablesRequest(BaseModel):
    features: Optional[List[str]] = None  # None = reset all stale features


class ResetVariablesResponse(BaseModel):
    status: str
    reset_variables: List[str] = []
    message: str


@router.post("/training/reset", response_model=ResetVariablesResponse)
async def reset_variables_to_snapshot(
    body: ResetVariablesRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Reset live variables to their values from the last training snapshot.

    This reverts configuration changes made since the last training,
    restoring variables to the "last known trained" state.

    Optionally filter by feature names to only reset specific features.
    """
    from zylch.agents.trainers import MrCallConfiguratorTrainer
    from zylch.tools.starchat import StarChatClient
    from zylch.config import settings

    owner_id = get_user_id_from_token(user)
    storage = get_storage()

    # Check MrCall is linked
    business_id = storage.get_mrcall_link(owner_id)
    if not business_id:
        raise HTTPException(status_code=400, detail="No MrCall assistant linked.")

    # Load snapshot
    snapshot = storage.get_training_snapshot(owner_id, business_id)
    if snapshot is None:
        raise HTTPException(status_code=400, detail="No training snapshot found. Train the agent first.")

    snapshot_variables = snapshot.get('variables', {})
    logger.debug(f"[training/reset] Loaded snapshot with {len(snapshot_variables)} variables")

    # Build StarChat client
    authorization = request.headers.get("authorization", "")
    firebase_token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization

    starchat = StarChatClient(
        base_url=settings.mrcall_base_url.rstrip('/'),
        auth_type="firebase",
        jwt_token=firebase_token,
        realm=settings.mrcall_realm,
        owner_id=owner_id,
    )

    # Fetch live variables to diff
    business = await starchat.get_business_config(business_id)
    if not business:
        raise HTTPException(status_code=400, detail="Business not found on StarChat.")

    live_variables = business.get("variables", {})

    # Diff to find what changed
    diff = MrCallConfiguratorTrainer.diff_snapshot(snapshot_variables, live_variables)

    # Filter by requested features if specified
    if body.features:
        for feat in body.features:
            if feat not in MrCallConfiguratorTrainer.FEATURES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown feature: {feat}. Available: {list(MrCallConfiguratorTrainer.FEATURES.keys())}"
                )
        variables_to_reset = [
            cv for cv in diff["changed_variables"]
            if cv["feature"] in body.features
        ]
    else:
        variables_to_reset = diff["changed_variables"]

    if not variables_to_reset:
        return ResetVariablesResponse(
            status="no_changes",
            reset_variables=[],
            message="No variables to reset — all values match the training snapshot.",
        )

    # Reset each changed variable to its snapshot value
    reset_names = []
    for cv in variables_to_reset:
        var_name = cv["name"]
        snapshot_val = cv["old_value"]  # old_value = snapshot value
        if snapshot_val is None:
            logger.debug(f"[training/reset] Skipping {var_name} — snapshot value is None")
            continue

        logger.debug(f"[training/reset] Resetting {var_name} to snapshot value")
        try:
            await starchat.update_business_variable(
                business_id=business_id,
                variable_name=var_name,
                value=snapshot_val,
            )
            reset_names.append(var_name)
            logger.info(f"[training/reset] Reset {var_name} to snapshot value")
        except Exception as e:
            logger.error(f"[training/reset] Failed to reset {var_name}: {e}")

    return ResetVariablesResponse(
        status="reset",
        reset_variables=reset_names,
        message=f"Reset {len(reset_names)} variable(s) to their trained values.",
    )
