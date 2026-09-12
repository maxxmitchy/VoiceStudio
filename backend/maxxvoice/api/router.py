"""MaxxVoice HTTP boundary for VoiceStudio and Careflux/WelLivox."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, status as http_status
from pydantic import BaseModel, Field

from maxxvoice.capabilities import VoiceCapabilityService
from maxxvoice.orchestration import MaxxVoicePlanner, MaxxVoiceWorkflowJobRunner
from maxxvoice.orchestration.jobs import JobStatus
from maxxvoice.orchestration.sqlite_jobs import SQLiteWorkflowJobStore
from maxxvoice.orchestration.sqlite_workflow_steps import SQLiteWorkflowStepStore, WorkflowStepCheckpoint
from maxxvoice.workflows import ArticlePodcastPlanner, ArticlePodcastRenderer, CarefluxVoiceRenderer

router = APIRouter(prefix="/maxxvoice", tags=["maxxvoice"])
_db_path = os.getenv("MAXXVOICE_JOB_DB", ".data/maxxvoice_jobs.sqlite3")
_artifact_dir = os.getenv("MAXXVOICE_ARTIFACT_DIR", ".data/maxxvoice_artifacts")
_workflow_store = SQLiteWorkflowJobStore(_db_path)
_step_store = SQLiteWorkflowStepStore(_db_path)
_workflow_runner = MaxxVoiceWorkflowJobRunner(_workflow_store)


class PlanRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=10_000)
    context: dict = Field(default_factory=dict)


class ArticlePodcastRequest(BaseModel):
    article: str = Field(min_length=1, max_length=500_000)
    title: str = Field(default="Untitled Podcast", max_length=500)
    target_duration_minutes: float = Field(default=10.0, gt=0, le=240)
    narrator: str = Field(default="narrator", min_length=1, max_length=200)
    chunk_words: int = Field(default=120, ge=20, le=2_000)
    language: str | None = Field(default=None, max_length=50)
    voice: str | None = Field(default=None, max_length=200)
    reference_audio: str | None = Field(default=None, max_length=4_000)
    synthesis_options: dict = Field(default_factory=dict)


class CarefluxVoiceRequest(BaseModel):
    # Presentation-only boundary: callers must provide already approved,
    # display-safe text rather than raw patient records or clinical context.
    text: str = Field(min_length=1, max_length=20_000)
    language: str | None = Field(default=None, max_length=50)
    voice: str | None = Field(default=None, max_length=200)
    direction: str | None = Field(default=None, max_length=1_000)
    reference_audio: str | None = Field(default=None, max_length=4_000)
    synthesis_options: dict = Field(default_factory=dict)


@router.get("/status")
def status():
    return {"name": "MaxxVoice", "version": "1", "mode": "careflux-ready",
            "job_store": "sqlite", "step_checkpoints": "sqlite", "segment_artifacts": "validated-wav",
            "capabilities": VoiceCapabilityService.capabilities(),
            "integrations": ["careflux-wellivox"]}


@router.post("/plan")
def plan(request: PlanRequest):
    return MaxxVoicePlanner().plan(request.goal, context=request.context).to_dict()


def _build_plan(payload: dict):
    return ArticlePodcastPlanner().plan(
        payload["article"], title=payload.get("title", "Untitled Podcast"),
        target_duration_minutes=payload.get("target_duration_minutes", 10.0),
        narrator=payload.get("narrator", "narrator"), chunk_words=payload.get("chunk_words", 120),
    )


async def _dispatch_article_podcast(job_id: str, podcast_plan) -> None:
    job = _workflow_store.get(job_id)
    if job is None:
        return

    async def operation():
        result = await ArticlePodcastRenderer().render(
            podcast_plan, language=job.payload.get("language"), voice=job.payload.get("voice"),
            reference_audio=job.payload.get("reference_audio"),
            synthesis_options=job.payload.get("synthesis_options") or {},
            checkpoint_store=_step_store, job_id=job_id, artifact_dir=_artifact_dir,
        )
        payload = result.to_dict()
        payload["plan"] = podcast_plan.to_dict()
        return payload

    await _workflow_runner.run("article-podcast", operation, job_id=job_id)


async def _dispatch_careflux_voice(job_id: str) -> None:
    job = _workflow_store.get(job_id)
    if job is None:
        return
    payload = job.payload
    artifact_path = str(Path(_artifact_dir) / "careflux" / f"{job_id}.wav")

    async def operation():
        result = await CarefluxVoiceRenderer().render(
            payload["text"], language=payload.get("language"), voice=payload.get("voice"),
            direction=payload.get("direction"), reference_audio=payload.get("reference_audio"),
            synthesis_options=payload.get("synthesis_options") or {}, artifact_path=artifact_path,
        )
        checkpoint = _step_store.get(job_id, "voice")
        if checkpoint is None:
            _step_store.upsert(WorkflowStepCheckpoint(job_id, "voice"))
        _step_store.mark_completed(job_id, "voice", result.to_dict())
        return result.to_dict()

    await _workflow_runner.run("careflux-voice", operation, job_id=job_id)


@router.post("/workflows/careflux-voice", status_code=http_status.HTTP_202_ACCEPTED)
async def careflux_voice(request: CarefluxVoiceRequest,
                         idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    """Render an approved Careflux message as speech without doing clinical reasoning."""
    payload = request.model_dump(mode="json")
    normalized_key = idempotency_key.strip() if idempotency_key else None
    if normalized_key:
        job, created = _workflow_store.create_or_get(
            "careflux-voice", payload=payload, idempotency_key=normalized_key
        )
    else:
        job = _workflow_runner.create("careflux-voice", payload=payload)
        created = True

    if _step_store.get(job.id, "voice") is None:
        _step_store.upsert(WorkflowStepCheckpoint(job.id, "voice"))
    if not created or job.status is not JobStatus.QUEUED:
        return _job_response(job)

    asyncio.create_task(_dispatch_careflux_voice(job.id))
    return _job_response(job)


@router.post("/workflows/article-podcast", status_code=http_status.HTTP_202_ACCEPTED)
async def article_podcast(request: ArticlePodcastRequest,
                          idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    normalized_key = idempotency_key.strip() if idempotency_key else None
    request_payload = request.model_dump(mode="json")
    podcast_plan = _build_plan(request_payload)
    if normalized_key:
        job, created = _workflow_store.create_or_get(
            "article-podcast", payload=request_payload, idempotency_key=normalized_key
        )
    else:
        job = _workflow_runner.create("article-podcast", payload=request_payload)
        created = True
    for segment in podcast_plan.segments:
        if _step_store.get(job.id, segment.id) is None:
            _step_store.upsert(WorkflowStepCheckpoint(job.id, segment.id))
    if not created or job.status is not JobStatus.QUEUED:
        return _job_response(job)
    asyncio.create_task(_dispatch_article_podcast(job.id, podcast_plan))
    return _job_response(job)


@router.post("/jobs/{job_id}/resume", status_code=http_status.HTTP_202_ACCEPTED)
async def resume_workflow_job(job_id: str):
    job = _workflow_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown workflow job: {job_id}")
    if job.workflow == "careflux-voice":
        if job.status is JobStatus.RUNNING or job.status is JobStatus.COMPLETED:
            return _job_response(job)
        if job.status is not JobStatus.FAILED:
            raise HTTPException(status_code=409, detail=f"Job is {job.status.value}; only failed jobs can be resumed.")
        job.status = JobStatus.QUEUED
        job.error = None
        job.completed_at = None
        job.started_at = None
        _workflow_store.update(job)
        asyncio.create_task(_dispatch_careflux_voice(job.id))
        return _job_response(job)
    if job.workflow != "article-podcast":
        raise HTTPException(status_code=400, detail="Resume is currently supported for MaxxVoice media workflows only.")
    if job.status is JobStatus.RUNNING or job.status is JobStatus.COMPLETED:
        return _job_response(job)
    if job.status is not JobStatus.FAILED:
        raise HTTPException(status_code=409, detail=f"Job is {job.status.value}; only failed jobs can be resumed.")
    podcast_plan = _build_plan(job.payload)
    job.status = JobStatus.QUEUED
    job.error = None
    job.completed_at = None
    job.started_at = None
    _workflow_store.update(job)
    for segment in podcast_plan.segments:
        if _step_store.get(job.id, segment.id) is None:
            _step_store.upsert(WorkflowStepCheckpoint(job.id, segment.id))
    asyncio.create_task(_dispatch_article_podcast(job.id, podcast_plan))
    return _job_response(job)


@router.get("/jobs/{job_id}")
def workflow_job(job_id: str):
    job = _workflow_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown workflow job: {job_id}")
    return _job_response(job)


def _job_response(job):
    payload = job.to_dict()
    steps = _step_store.list(job.id)
    completed = sum(step.status == "completed" for step in steps)
    total = len(steps)
    running = next((step.step_id for step in steps if step.status == "running"), None)
    payload["progress"] = {"completed": completed, "total": total,
                           "percent": round((completed / total) * 100, 1) if total else 100.0,
                           "current_step": running, "steps": [step.to_dict() for step in steps]}
    return payload
