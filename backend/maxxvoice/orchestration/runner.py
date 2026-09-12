"""Job-aware execution orchestration for MaxxVoice.

This layer binds the stateless executor to job state. It intentionally keeps
storage injectable so the in-memory store can later be replaced by durable
SQLite/queue infrastructure without changing the workflow contract.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from maxxvoice.orchestration.executor import MaxxVoiceExecutor
from maxxvoice.orchestration.jobs import (
    InMemoryJobStore,
    JobState,
    JobStatus,
    StepStatus,
)
from maxxvoice.orchestration.planner import Plan


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MaxxVoiceJobRunner:
    """Create and execute plans while recording workflow state."""

    def __init__(
        self,
        *,
        store: InMemoryJobStore | None = None,
        executor: MaxxVoiceExecutor | None = None,
    ) -> None:
        self.store = store or InMemoryJobStore()
        self.executor = executor or MaxxVoiceExecutor()

    def create(self, plan: Plan, *, job_id: str | None = None) -> JobState:
        """Create a queued job without executing any capability."""
        return self.store.create(plan, job_id=job_id)

    async def run(
        self,
        plan: Plan,
        *,
        context: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> JobState:
        """Execute a plan and reconcile its result into job state."""
        job = self.create(plan, job_id=job_id)
        job.status = JobStatus.RUNNING
        job.started_at = _now()
        self.store.update(job)

        result = await self.executor.execute(plan, context=context)

        completed = set(result.completed_steps)
        for step in job.steps:
            if step.step_id in completed:
                step.status = StepStatus.COMPLETED
                step.completed_at = _now()
                step.artifact = result.artifacts.get(step.step_id)
            elif result.status == "failed" and not step.error:
                # The executor stops at the first failure. The first non-completed
                # step is the actionable failure boundary; later steps remain pending.
                if not job.errors:
                    step.status = StepStatus.FAILED
                    step.error = result.errors[0] if result.errors else "Step failed."

        job.artifacts.update(result.artifacts)
        job.errors.extend(result.errors)
        job.status = (
            JobStatus.COMPLETED
            if result.status == "completed"
            else JobStatus.FAILED
        )
        job.completed_at = _now()
        self.store.update(job)
        return job
