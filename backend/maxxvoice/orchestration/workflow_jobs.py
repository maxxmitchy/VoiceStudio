"""Job lifecycle support for MaxxVoice workflows.

This module deliberately sits beside the capability-oriented job runner.
Capability plans use :class:`MaxxVoiceJobRunner`; higher-level workflows such
as Article -> Podcast have their own production plan and renderer, so they
should not be forced through the generic capability executor.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional
from uuid import uuid4

from .jobs import InMemoryJobStore, JobStatus


class WorkflowJobError(RuntimeError):
    """Raised for invalid workflow-job operations."""


@dataclass
class WorkflowJob:
    """Transport-neutral state for one higher-level workflow execution."""

    id: str
    workflow: str
    status: JobStatus = JobStatus.QUEUED
    created_at: str = field(default_factory=lambda: _now())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "workflow": self.workflow,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "error": self.error,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryWorkflowJobStore:
    """Small injectable store used by the HTTP layer and tests.

    Persistence is intentionally not coupled to FastAPI. A SQLite/queue-backed
    implementation can replace this store later without changing workflow
    contracts.
    """

    def __init__(self) -> None:
        self._jobs: Dict[str, WorkflowJob] = {}

    def create(self, workflow: str, job_id: Optional[str] = None) -> WorkflowJob:
        job = WorkflowJob(id=job_id or uuid4().hex, workflow=workflow)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Optional[WorkflowJob]:
        return self._jobs.get(job_id)

    def require(self, job_id: str) -> WorkflowJob:
        job = self.get(job_id)
        if job is None:
            raise WorkflowJobError(f"Unknown workflow job: {job_id}")
        return job


RunnerCallable = Callable[[], Any | Awaitable[Any]]


class MaxxVoiceWorkflowJobRunner:
    """Execute a high-level workflow while recording observable job state."""

    def __init__(self, store: Optional[InMemoryWorkflowJobStore] = None) -> None:
        self.store = store or InMemoryWorkflowJobStore()

    def create(self, workflow: str, job_id: Optional[str] = None) -> WorkflowJob:
        if not workflow.strip():
            raise WorkflowJobError("workflow must not be empty")
        return self.store.create(workflow, job_id=job_id)

    async def run(
        self,
        workflow: str,
        operation: RunnerCallable,
        *,
        job_id: Optional[str] = None,
    ) -> WorkflowJob:
        job = self.create(workflow, job_id=job_id)
        job.status = JobStatus.RUNNING
        job.started_at = _now()

        try:
            value = operation()
            if inspect.isawaitable(value):
                value = await value
            job.result = _to_dict(value)
            job.status = JobStatus.COMPLETED
        except Exception as exc:  # noqa: BLE001 - lifecycle must capture failures
            job.error = str(exc)
            job.status = JobStatus.FAILED
        finally:
            job.completed_at = _now()

        return job


def _to_dict(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return value
    return {"value": value}
