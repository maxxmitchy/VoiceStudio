"""SQLite-backed workflow job persistence for MaxxVoice."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from .jobs import JobStatus
from .workflow_jobs import WorkflowJob, _now


class SQLiteWorkflowJobStore:
    """Durable workflow-job store with atomic idempotent creation/claiming."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("""
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
            """)
            columns = {row["name"] for row in connection.execute(
                "PRAGMA table_info(maxxvoice_workflow_jobs)"
            ).fetchall()}
            if "payload_json" not in columns:
                connection.execute("ALTER TABLE maxxvoice_workflow_jobs ADD COLUMN payload_json TEXT")
            if "idempotency_key" not in columns:
                connection.execute("ALTER TABLE maxxvoice_workflow_jobs ADD COLUMN idempotency_key TEXT")
            connection.commit()

    def create(
        self,
        workflow: str,
        job_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> WorkflowJob:
        job, _ = self.create_or_get(
            workflow, job_id=job_id, payload=payload, idempotency_key=idempotency_key
        )
        return job

    def create_or_get(
        self,
        workflow: str,
        job_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> tuple[WorkflowJob, bool]:
        job = WorkflowJob(
            id=job_id or uuid4().hex,
            workflow=workflow,
            payload=dict(payload or {}),
            idempotency_key=idempotency_key,
        )
        connection = self._connect()
        try:
            # BEGIN IMMEDIATE serializes competing creators so the idempotency
            # key is decided once, before either request can dispatch work.
            connection.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                row = connection.execute(
                    """SELECT * FROM maxxvoice_workflow_jobs
                       WHERE workflow = ? AND idempotency_key = ?""",
                    (workflow, idempotency_key),
                ).fetchone()
                if row is not None:
                    return self._from_row(row), False
            connection.execute(
                """INSERT INTO maxxvoice_workflow_jobs
                   (id, workflow, status, created_at, started_at, completed_at,
                    result_json, error, payload_json, idempotency_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job.id, job.workflow, job.status.value, job.created_at,
                    job.started_at, job.completed_at,
                    json.dumps(job.result, ensure_ascii=False) if job.result is not None else None,
                    job.error,
                    json.dumps(job.payload, ensure_ascii=False),
                    job.idempotency_key,
                ),
            )
            connection.commit()
            return job, True
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(self, job_id: str) -> Optional[WorkflowJob]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM maxxvoice_workflow_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def get_by_idempotency_key(self, workflow: str, idempotency_key: str) -> Optional[WorkflowJob]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM maxxvoice_workflow_jobs WHERE workflow = ? AND idempotency_key = ?",
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
                """UPDATE maxxvoice_workflow_jobs
                   SET workflow = ?, status = ?, created_at = ?, started_at = ?,
                       completed_at = ?, result_json = ?, error = ?,
                       payload_json = ?, idempotency_key = ? WHERE id = ?""",
                (
                    job.workflow, job.status.value, job.created_at, job.started_at,
                    job.completed_at,
                    json.dumps(job.result, ensure_ascii=False) if job.result is not None else None,
                    job.error, json.dumps(job.payload, ensure_ascii=False),
                    job.idempotency_key, job.id,
                ),
            )
            connection.commit()
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown workflow job: {job.id}")
        return job

    @staticmethod
    def _from_row(row: sqlite3.Row) -> WorkflowJob:
        return WorkflowJob(
            id=row["id"], workflow=row["workflow"], status=JobStatus(row["status"]),
            created_at=row["created_at"], started_at=row["started_at"],
            completed_at=row["completed_at"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"],
            payload=json.loads(row["payload_json"]) if row["payload_json"] else {},
            idempotency_key=row["idempotency_key"],
        )
