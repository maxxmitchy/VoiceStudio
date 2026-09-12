from __future__ import annotations

from maxxvoice.orchestration.sqlite_workflow_steps import (
    SQLiteWorkflowStepStore,
    WorkflowStepStatus,
)


def test_workflow_step_checkpoint_survives_store_reopen(tmp_path):
    db = tmp_path / "jobs.sqlite3"
    store = SQLiteWorkflowStepStore(db)

    store.mark_running("job-1", "segment-001")
    store.mark_completed(
        "job-1",
        "segment-001",
        {"samples": 1000, "sample_rate": 1000, "engine_id": "fake"},
    )

    reopened = SQLiteWorkflowStepStore(db)
    checkpoint = reopened.get("job-1", "segment-001")

    assert checkpoint is not None
    assert checkpoint.status == WorkflowStepStatus.COMPLETED
    assert checkpoint.artifact == {
        "samples": 1000,
        "sample_rate": 1000,
        "engine_id": "fake",
    }


def test_failed_step_is_durable(tmp_path):
    store = SQLiteWorkflowStepStore(tmp_path / "jobs.sqlite3")
    store.mark_failed("job-2", "segment-002", "synthesis failed")

    checkpoint = store.get("job-2", "segment-002")

    assert checkpoint is not None
    assert checkpoint.status == WorkflowStepStatus.FAILED
    assert checkpoint.error == "synthesis failed"
