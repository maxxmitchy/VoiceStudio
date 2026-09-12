"""SQLite-backed workflow job persistence for MaxxVoice.

The store implements the same small contract as the in-memory workflow store,
so the API/runner can move from development storage to durable storage without
changing workflow semantics.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from .workflow_jobs import WorkflowJob


class SQLiteWorkflowJobStore:
    """Durable workflow-job store using a single SQLite database."""

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
                CREATE TABLE IF NOT EXISTS maxxvoice_workflow_jobs (
                    id TEXT PRIMARY KEY,
                    workflow TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    result_json TEXT,
                    error TEXT
                )
                """
            )
            connection.commit()

    def create(self, job: WorkflowJob) -> WorkflowJob:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO maxxvoice_workflow_jobs
                (id, workflow, status, created_at, started_at, completed_at,
                 result_json, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.workflow,
                    job.status.value,
                    job.created_at,
                    job.started_at,
                    job.completed_at,
                    json.dumps(job.result) if job.result is not None else None,
                    job.error,
                ),
            )
            connection.commit()
        return job

    def get(self, job_id: str) -> Optional[WorkflowJob]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM maxxvoice_workflow_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def require(self, job_id: str) -> WorkflowJob:
        job = self.get(job_id)
        if job is None:
            raise KeyError(f"Unknown workflow job: {job_id}")
        return job

    def update(self, job: WorkflowJob) -> WorkflowJob:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE maxxvoice_workflow_jobs
                SET workflow = ?, status = ?, created_at = ?, started_at = ?,
                    completed_at = ?, result_json = ?, error = ?
                WHERE id = ?
                """,
                (
                    job.workflow,
                    job.status.value,
                    job.created_at,
                    job.started_at,
                    job.completed_at,
                    json.dumps(job.result) if job.result is not None else None,
                    job.error,
                    job.id,
                ),
            )
            connection.commit()
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown workflow job: {job.id}")
        return job

    @staticmethod
    def _from_row(row: sqlite3.Row) -> WorkflowJob:
        return WorkflowJob(
            id=row["id"],
            workflow=row["workflow"],
            status=row["status"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"],
        )
