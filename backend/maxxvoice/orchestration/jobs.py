"""Job and workflow state primitives for MaxxVoice.

This module deliberately keeps persistence out of the first job-state milestone.
The state model is transport/storage agnostic so it can later be backed by the
existing SQLite layer or a queue without changing the orchestration contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from maxxvoice.orchestration.planner import Plan


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class JobStepState:
    step_id: str
    capability: str
    status: StepStatus = StepStatus.PENDING
    started_at: str | None = None
    completed_at: str | None = None
    artifact: Any = None
    error: str | None = None


@dataclass(slots=True)
class JobState:
    id: str
    goal: str
    plan_version: str
    status: JobStatus = JobStatus.QUEUED
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    completed_at: str | None = None
    steps: list[JobStepState] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_plan(cls, plan: Plan, *, job_id: str | None = None) -> "JobState":
        return cls(
            id=job_id or str(uuid4()),
            goal=plan.goal,
            plan_version=plan.version,
            steps=[
                JobStepState(step_id=s.id, capability=s.capability)
                for s in plan.steps
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "plan_version": self.plan_version,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "steps": [
                {
                    "step_id": s.step_id,
                    "capability": s.capability,
                    "status": s.status.value,
                    "started_at": s.started_at,
                    "completed_at": s.completed_at,
                    "artifact": s.artifact,
                    "error": s.error,
                }
                for s in self.steps
            ],
            "artifacts": self.artifacts,
            "errors": self.errors,
        }


class InMemoryJobStore:
    """Small state store for the first workflow milestone.

    It is intentionally replaceable. The API can depend on this interface while
    a later SQLite-backed implementation provides durable jobs and resume support.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}

    def create(self, plan: Plan, *, job_id: str | None = None) -> JobState:
        job = JobState.from_plan(plan, job_id=job_id)
        if job.id in self._jobs:
            raise ValueError(f"Job '{job.id}' already exists.")
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> JobState | None:
        return self._jobs.get(job_id)

    def require(self, job_id: str) -> JobState:
        job = self.get(job_id)
        if job is None:
            raise KeyError(f"Job '{job_id}' was not found.")
        return job

    def update(self, job: JobState) -> JobState:
        self._jobs[job.id] = job
        return job

    def list(self) -> list[JobState]:
        return list(self._jobs.values())
