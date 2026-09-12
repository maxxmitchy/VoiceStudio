from maxxvoice.orchestration.jobs import JobStatus
from maxxvoice.orchestration.sqlite_jobs import SQLiteWorkflowJobStore


def test_sqlite_store_survives_new_store_instance(tmp_path):
    path = tmp_path / "jobs.sqlite3"
    store = SQLiteWorkflowJobStore(path)

    created = store.create(
        "article-podcast",
        payload={"title": "Demo", "target_duration_minutes": 10},
        idempotency_key="request-123",
    )
    created.status = JobStatus.COMPLETED
    created.result = {"artifact": "demo.wav"}
    store.update(created)

    reopened = SQLiteWorkflowJobStore(path)
    loaded = reopened.get(created.id)

    assert loaded is not None
    assert loaded.status is JobStatus.COMPLETED
    assert loaded.payload["title"] == "Demo"
    assert loaded.result == {"artifact": "demo.wav"}
    assert loaded.idempotency_key == "request-123"


def test_sqlite_store_returns_existing_job_for_idempotency_key(tmp_path):
    store = SQLiteWorkflowJobStore(tmp_path / "jobs.sqlite3")

    first = store.create("article-podcast", idempotency_key="same-request")
    second = store.create(
        "article-podcast",
        payload={"different": True},
        idempotency_key="same-request",
    )

    assert second.id == first.id
    assert second.payload == first.payload


def test_sqlite_store_allows_same_key_for_different_workflows(tmp_path):
    store = SQLiteWorkflowJobStore(tmp_path / "jobs.sqlite3")

    first = store.create("article-podcast", idempotency_key="same-request")
    second = store.create("other-workflow", idempotency_key="same-request")

    assert first.id != second.id
