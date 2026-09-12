from __future__ import annotations

import pytest

from maxxvoice.orchestration.workflow_jobs import (
    InMemoryWorkflowJobStore,
    MaxxVoiceWorkflowJobRunner,
    WorkflowJobError,
)


@pytest.mark.asyncio
async def test_workflow_runner_records_success_and_result() -> None:
    store = InMemoryWorkflowJobStore()
    runner = MaxxVoiceWorkflowJobRunner(store)

    async def operation():
        return {"artifact": "podcast.wav"}

    job = await runner.run("article-podcast", operation)

    assert job.status.value == "completed"
    assert job.result == {"artifact": "podcast.wav"}
    assert job.error is None
    assert job.started_at is not None
    assert job.completed_at is not None
    assert store.require(job.id) is job


@pytest.mark.asyncio
async def test_workflow_runner_records_failure_without_raising() -> None:
    runner = MaxxVoiceWorkflowJobRunner()

    async def operation():
        raise RuntimeError("render failed")

    job = await runner.run("article-podcast", operation)

    assert job.status.value == "failed"
    assert job.error == "render failed"
    assert job.result is None
    assert job.completed_at is not None


def test_empty_workflow_is_rejected() -> None:
    runner = MaxxVoiceWorkflowJobRunner()

    with pytest.raises(WorkflowJobError):
        runner.create("   ")
