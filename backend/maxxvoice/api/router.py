"""MaxxVoice HTTP boundary.

The router exposes deterministic planning plus explicit workflow execution.
Workflow requests are represented as durable jobs so long-running speech
generation does not block the HTTP request until rendering completes.
"""
from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, Header, HTTPException, status as http_status
from pydantic import BaseModel, Field

from maxxvoice.capabilities import VoiceCapabilityService
from maxxvoice.orchestration import MaxxVoicePlanner, MaxxVoiceWorkflowJobRunner
from maxxvoice.orchestration.jobs import JobStatus
from maxxvoice.orchestration.sqlite_jobs import SQLiteWorkflowJobStore
from maxxvoice.orchestration.sqlite_workflow_steps import SQLiteWorkflowStepStore, WorkflowStepCheckpoint
from maxxvoice.workflows import ArticlePodcastPlanner, ArticlePodcastRenderer

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


@router.get("/status")
def status():
    return {"name": "MaxxVoice", "version": "1", "mode": "orchestration-foundation",
            "job_store": "sqlite", "step_checkpoints": "sqlite", "segment_artifacts": "validated-wav",
            "capabilities": VoiceCapabilityService.capabilities()}


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


@router.post("/workflows/article-podcast", status_code=http_status.HTTP_202_ACCEPTED)
async def article_podcast(request: ArticlePodcastRequest,
                          idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    normalized_key = idempotency_key.strip() if idempotency_key else None
    podcast_plan = _build_plan(request.model_dump(mode="json"))

    if normalized_key:
        job, created = _workflow_store.create_or_get(
            "article-podcast", payload=request.model_dump(mode="json"), idempotency_key=normalized_key
        )
    else:
        job = _workflow_runner.create("article-podcast", payload=request.model_dump(mode="json"))
        created = True

    for segment in podcast_plan.segments:
        if _step_store.get(job.id, segment.id) is None:
            _step_store.upsert(WorkflowStepCheckpoint(job.id, segment.id))

    # Only the request that atomically created the job may dispatch it.
    if not created or job.status is not JobStatus.QUEUED:
        return _job_response(job)

    asyncio.create_task(_dispatch_article_podcast(job.id, podcast_plan))
    return _job_response(job)


@router.post("/jobs/{job_id}/resume", status_code=http_status.HTTP_202_ACCEPTED)
async def resume_workflow_job(job_id: str):
    job = _workflow_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown workflow job: {job_id}")
    if job.workflow != "article-podcast":
        raise HTTPException(status_code=400, detail="Resume is currently supported for article-podcast jobs only.")
    if job.status is JobStatus.RUNNING:
        return _job_response(job)
    if job.status is JobStatus.COMPLETED:
        return _job_response(job)
    if job.status is not JobStatus.FAILED:
        raise HTTPException(status_code=409, detail=f"Job is {job.status.value}; only failed jobs can be resumed.")
    podcast_plan = _build_plan(job.payload)
    job.status = JobStatus.QUEUED
    job.error = None
    job.completed_at = None
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
    payload["progress"] = {
        "completed": completed, "total": total,
        "percent": round((completed / total) * 100, 1) if total else 100.0,
        "current_step": running, "steps": [step.to_dict() for step in steps],
    }
    return payload
