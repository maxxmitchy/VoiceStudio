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
from maxxvoice.workflows import ArticlePodcastPlanner, ArticlePodcastRenderer

router = APIRouter(prefix="/maxxvoice", tags=["maxxvoice"])

_db_path = os.getenv("MAXXVOICE_JOB_DB", ".data/maxxvoice_jobs.sqlite3")
_workflow_store = SQLiteWorkflowJobStore(_db_path)
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
    return {
        "name": "MaxxVoice",
        "version": "1",
        "mode": "orchestration-foundation",
        "job_store": "sqlite",
        "capabilities": VoiceCapabilityService.capabilities(),
    }


@router.post("/plan")
def plan(request: PlanRequest):
    return MaxxVoicePlanner().plan(request.goal, context=request.context).to_dict()


@router.post(
    "/workflows/article-podcast",
    status_code=http_status.HTTP_202_ACCEPTED,
)
async def article_podcast(
    request: ArticlePodcastRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Create an Article -> Podcast job and dispatch rendering in the background."""
    podcast_plan = ArticlePodcastPlanner().plan(
        request.article,
        title=request.title,
        target_duration_minutes=request.target_duration_minutes,
        narrator=request.narrator,
        chunk_words=request.chunk_words,
    )

    job = _workflow_runner.create(
        "article-podcast",
        payload=request.model_dump(mode="json"),
        idempotency_key=idempotency_key,
    )

    # An idempotent retry must not schedule the same work twice.
    if job.status is not JobStatus.QUEUED:
        return job.to_dict()

    async def operation():
        result = await ArticlePodcastRenderer().render(
            podcast_plan,
            language=request.language,
            voice=request.voice,
            reference_audio=request.reference_audio,
            synthesis_options=request.synthesis_options,
        )
        payload = result.to_dict()
        payload["plan"] = podcast_plan.to_dict()
        return payload

    async def dispatch() -> None:
        await _workflow_runner.run(
            "article-podcast",
            operation,
            job_id=job.id,
        )

    asyncio.create_task(dispatch())
    return job.to_dict()


@router.get("/jobs/{job_id}")
def workflow_job(job_id: str):
    """Return the current state/result of a MaxxVoice workflow job."""
    job = _workflow_store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Unknown workflow job: {job_id}",
        )
    return job.to_dict()
