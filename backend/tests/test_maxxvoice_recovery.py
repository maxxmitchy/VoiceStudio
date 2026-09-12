from maxxvoice.orchestration.jobs import JobStatus
from maxxvoice.orchestration.recovery import RECOVERY_ERROR, recover_interrupted_jobs
from maxxvoice.orchestration.workflow_jobs import InMemoryWorkflowJobStore


def test_recover_interrupted_running_jobs() -> None:
    store = InMemoryWorkflowJobStore()
    running = store.create("article-podcast", payload={"article": "hello"})
    running.status = JobStatus.RUNNING
    store.update(running)
    completed = store.create("article-podcast")
    completed.status = JobStatus.COMPLETED
    store.update(completed)

    recovered = recover_interrupted_jobs(store)

    assert [job.id for job in recovered] == [running.id]
    assert store.get(running.id).status is JobStatus.FAILED
    assert store.get(running.id).error == RECOVERY_ERROR
    assert store.get(completed.id).status is JobStatus.COMPLETED


def test_recovery_is_idempotent() -> None:
    store = InMemoryWorkflowJobStore()
    job = store.create("article-podcast")
    job.status = JobStatus.RUNNING
    store.update(job)

    assert len(recover_interrupted_jobs(store)) == 1
    assert len(recover_interrupted_jobs(store)) == 0
