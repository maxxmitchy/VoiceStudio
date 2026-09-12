"""Job lifecycle support for MaxxVoice workflows."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional, Protocol
from uuid import uuid4

from .jobs import JobStatus


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
    payload: Dict[str, Any] = field(default_factory=dict)
    idempotency_key: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "workflow": self.workflow, "status": self.status.value,
            "created_at": self.created_at, "started_at": self.started_at,
            "completed_at": self.completed_at, "result": self.result,
            "error": self.error, "payload": self.payload,
            "idempotency_key": self.idempotency_key,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowJobStore(Protocol):
    def create(self, workflow: str, job_id: Optional[str] = None,
               payload: Optional[Dict[str, Any]] = None,
               idempotency_key: Optional[str] = None) -> WorkflowJob: ...
    def get(self, job_id: str) -> Optional[WorkflowJob]: ...
    def get_by_idempotency_key(self, workflow: str, idempotency_key: str) -> Optional[WorkflowJob]: ...
    def update(self, job: WorkflowJob) -> WorkflowJob: ...


class InMemoryWorkflowJobStore:
    """Development store implementing the workflow-store contract."""
    def __init__(self) -> None:
        self._jobs: Dict[str, WorkflowJob] = {}

    def create(self, workflow: str, job_id: Optional[str] = None,
               payload: Optional[Dict[str, Any]] = None,
               idempotency_key: Optional[str] = None) -> WorkflowJob:
        job, _ = self.create_or_get(workflow, job_id, payload, idempotency_key)
        return job

    def create_or_get(self, workflow: str, job_id: Optional[str] = None,
                      payload: Optional[Dict[str, Any]] = None,
                      idempotency_key: Optional[str] = None) -> tuple[WorkflowJob, bool]:
        if idempotency_key:
            existing = self.get_by_idempotency_key(workflow, idempotency_key)
            if existing is not None:
                return existing, False
        job = WorkflowJob(id=job_id or uuid4().hex, workflow=workflow,
                          payload=dict(payload or {}), idempotency_key=idempotency_key)
        if job.id in self._jobs:
            raise WorkflowJobError(f"Workflow job already exists: {job.id}")
        self._jobs[job.id] = job
        return job, True

    def get(self, job_id: str) -> Optional[WorkflowJob]:
        return self._jobs.get(job_id)

    def get_by_idempotency_key(self, workflow: str, idempotency_key: str) -> Optional[WorkflowJob]:
        for job in self._jobs.values():
            if job.workflow == workflow and job.idempotency_key == idempotency_key:
                return job
        return None

    def require(self, job_id: str) -> WorkflowJob:
        job = self.get(job_id)
        if job is None:
            raise WorkflowJobError(f"Unknown workflow job: {job_id}")
        return job

    def update(self, job: WorkflowJob) -> WorkflowJob:
        if job.id not in self._jobs:
            raise WorkflowJobError(f"Unknown workflow job: {job.id}")
        self._jobs[job.id] = job
        return job


RunnerCallable = Callable[[], Any | Awaitable[Any]]


class MaxxVoiceWorkflowJobRunner:
    """Execute a high-level workflow while recording observable job state."""
    def __init__(self, store: Optional[WorkflowJobStore] = None) -> None:
        self.store = store or InMemoryWorkflowJobStore()

    def create(self, workflow: str, job_id: Optional[str] = None,
               payload: Optional[Dict[str, Any]] = None,
               idempotency_key: Optional[str] = None) -> WorkflowJob:
        if not workflow.strip():
            raise WorkflowJobError("workflow must not be empty")
        return self.store.create(workflow, job_id=job_id, payload=payload,
                                 idempotency_key=idempotency_key)

    async def run(self, workflow: str, operation: RunnerCallable,
                  *, job_id: Optional[str] = None) -> WorkflowJob:
        if job_id is not None:
            job = self.store.get(job_id)
            if job is None:
                raise WorkflowJobError(f"Unknown workflow job: {job_id}")
            if job.workflow != workflow:
                raise WorkflowJobError(f"Workflow job {job_id} belongs to {job.workflow!r}, not {workflow!r}")
            if job.status is not JobStatus.QUEUED:
                raise WorkflowJobError(f"Workflow job {job_id} is already {job.status.value}")
        else:
            job = self.create(workflow)
        job.status = JobStatus.RUNNING
        job.started_at = _now()
        self.store.update(job)
        try:
            value = operation()
            if inspect.isawaitable(value):
                value = await value
            job.result = _to_dict(value)
            job.status = JobStatus.COMPLETED
        except Exception as exc:
            job.error = str(exc)
            job.status = JobStatus.FAILED
        finally:
            job.completed_at = _now()
            self.store.update(job)
        return job


def _to_dict(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return value
    return {"value": value}
