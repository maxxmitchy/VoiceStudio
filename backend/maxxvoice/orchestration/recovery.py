"""Startup recovery helpers for durable MaxxVoice workflow jobs.

Recovery is intentionally conservative: a process restart must never claim that
GPU work continued. Interrupted running jobs are converted to failed jobs while
validated segment checkpoints remain available to the explicit resume endpoint.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .jobs import JobStatus


RECOVERY_ERROR = "workflow interrupted by process restart; validated checkpoints are available for resume"


def recover_interrupted_jobs(job_store: Any) -> list[Any]:
    """Mark durable RUNNING jobs as FAILED after an application restart.

    The operation is idempotent and deliberately does not execute work. A later
    resume request can reconstruct the workflow from the persisted payload and
    reuse only validated segment artifacts.
    """
    recovered = []
    jobs = job_store.list() if hasattr(job_store, "list") else []
    for job in jobs:
        if job.status is not JobStatus.RUNNING:
            continue
        job.status = JobStatus.FAILED
        job.error = RECOVERY_ERROR
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job_store.update(job)
        recovered.append(job)
    return recovered
