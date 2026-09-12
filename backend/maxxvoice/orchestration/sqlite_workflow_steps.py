"""Durable per-step checkpoints for long-running MaxxVoice workflows."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class WorkflowStepStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class WorkflowStepCheckpoint:
    job_id: str
    step_id: str
    status: str = WorkflowStepStatus.PENDING
    started_at: str | None = None
    completed_at: str | None = None
    artifact: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "step_id": self.step_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "artifact": self.artifact,
            "error": self.error,
        }


class SQLiteWorkflowStepStore:
    """Persist workflow-step checkpoints in the same SQLite DB as jobs."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS maxxvoice_workflow_steps (
                    job_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    artifact_json TEXT,
                    error TEXT,
                    PRIMARY KEY (job_id, step_id)
                )
                """
            )
            connection.commit()

    def get(self, job_id: str, step_id: str) -> WorkflowStepCheckpoint | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM maxxvoice_workflow_steps WHERE job_id = ? AND step_id = ?",
                (job_id, step_id),
            ).fetchone()
        return self._from_row(row) if row else None

    def list(self, job_id: str) -> list[WorkflowStepCheckpoint]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM maxxvoice_workflow_steps WHERE job_id = ? ORDER BY rowid",
                (job_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def upsert(self, checkpoint: WorkflowStepCheckpoint) -> WorkflowStepCheckpoint:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO maxxvoice_workflow_steps
                (job_id, step_id, status, started_at, completed_at, artifact_json, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, step_id) DO UPDATE SET
                    status = excluded.status,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at,
                    artifact_json = excluded.artifact_json,
                    error = excluded.error
                """,
                (
                    checkpoint.job_id,
                    checkpoint.step_id,
                    checkpoint.status,
                    checkpoint.started_at,
                    checkpoint.completed_at,
                    json.dumps(checkpoint.artifact, ensure_ascii=False)
                    if checkpoint.artifact is not None else None,
                    checkpoint.error,
                ),
            )
            connection.commit()
        return checkpoint

    def mark_running(self, job_id: str, step_id: str) -> WorkflowStepCheckpoint:
        current = self.get(job_id, step_id) or WorkflowStepCheckpoint(job_id, step_id)
        current.status = WorkflowStepStatus.RUNNING
        current.started_at = current.started_at or _now()
        current.completed_at = None
        current.error = None
        return self.upsert(current)

    def mark_completed(
        self, job_id: str, step_id: str, artifact: dict[str, Any] | None = None
    ) -> WorkflowStepCheckpoint:
        current = self.get(job_id, step_id) or WorkflowStepCheckpoint(job_id, step_id)
        current.status = WorkflowStepStatus.COMPLETED
        current.started_at = current.started_at or _now()
        current.completed_at = _now()
        current.artifact = artifact
        current.error = None
        return self.upsert(current)

    def mark_failed(self, job_id: str, step_id: str, error: str) -> WorkflowStepCheckpoint:
        current = self.get(job_id, step_id) or WorkflowStepCheckpoint(job_id, step_id)
        current.status = WorkflowStepStatus.FAILED
        current.started_at = current.started_at or _now()
        current.completed_at = _now()
        current.error = error
        return self.upsert(current)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> WorkflowStepCheckpoint:
        return WorkflowStepCheckpoint(
            job_id=row["job_id"],
            step_id=row["step_id"],
            status=row["status"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            artifact=json.loads(row["artifact_json"]) if row["artifact_json"] else None,
            error=row["error"],
        )
