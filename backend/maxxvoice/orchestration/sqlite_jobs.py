"""SQLite-backed workflow job persistence for MaxxVoice.

The store implements the same contract as the in-memory workflow store so the
API/runner can use durable storage without changing workflow semantics.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional
from uuid import uuid4

from .jobs import JobStatus
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
                    error TEXT,
                    payload_json TEXT,
                    idempotency_key TEXT,
                    UNIQUE(workflow, idempotency_key)
                )
                """
            )
            # Older development databases may predate the payload columns.
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(maxxvoice_workflow_jobs)"
                ).fetchall()
            }
            if "payload_json" not in columns:
                connection.execute(
                    "ALTER TABLE maxxvoice_workflow_jobs ADD COLUMN payload_json TEXT"
                )
            if "idempotency_key" not in columns:
                connection.execute(
                    "ALTER TABLE maxxvoice_workflow_jobs ADD COLUMN idempotency_key TEXT"
                )
            connection.commit()

    def create(
        self,
        workflow: str,
        job_id: Optional[str] = None,
        payload: Optional[dict] = None,
        idempotency_key: Optional[str] = None,
    ) -> WorkflowJob:
        if idempotency_key:
            existing = self.get_by_idempotency_key(workflow, idempotency_key)
            if existing is not None:
                return existing
        job = WorkflowJob(
            id=job_id or uuid4().hex,
            workflow=workflow,
            payload=dict(payload or {}),
            idempotency_key=idempotency_key,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO maxxvoice_workflow_jobs
                (id, workflow, status, created_at, started_at, completed_at,
                 result_json, error, payload_json, idempotency_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps(job.payload, ensure_ascii=False),
                    job.idempotency_key,
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

    def get_by_idempotency_key(
        self, workflow: str, idempotency_key: str
    ) -> Optional[WorkflowJob]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM maxxvoice_workflow_jobs
                WHERE workflow = ? AND idempotency_key = ?
                """,
                (workflow, idempotency_key),
            ).fetchone()
        return self._from_row(row) if row is not None else None

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
                    completed_at = ?, result_json = ?, error = ?,
                    payload_json = ?, idempotency_key = ?
                WHERE id = ?
                """,
                (
                    job.workflow,
                    job.status.value,
                    job.created_at,
                    job.started_at,
                    job.completed_at,
                    json.dumps(job.result, ensure_ascii=False)
                    if job.result is not None else None,
                    job.error,
                    json.dumps(job.payload, ensure_ascii=False),
                    job.idempotency_key,
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
            status=JobStatus(row["status"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"],
            payload=json.loads(row["payload_json"]) if row["payload_json"] else {},
            idempotency_key=row["idempotency_key"],
        )
