from maxxvoice.orchestration import (
    InMemoryJobStore,
    JobStatus,
    MaxxVoicePlanner,
    StepStatus,
)


def test_job_is_created_from_plan_with_pending_steps():
    plan = MaxxVoicePlanner().plan("Transcribe this recording")
    job = InMemoryJobStore().create(plan, job_id="job-1")

    assert job.id == "job-1"
    assert job.status == JobStatus.QUEUED
    assert job.steps[0].step_id == "transcribe"
    assert job.steps[0].status == StepStatus.PENDING


def test_job_state_serializes_for_api_storage():
    plan = MaxxVoicePlanner().plan("Create a voice-over")
    job = InMemoryJobStore().create(plan, job_id="job-2")

    payload = job.to_dict()

    assert payload["id"] == "job-2"
    assert payload["status"] == "queued"
    assert payload["steps"][0]["capability"] == "synthesize"


def test_store_rejects_duplicate_ids():
    plan = MaxxVoicePlanner().plan("Transcribe this recording")
    store = InMemoryJobStore()
    store.create(plan, job_id="job-3")

    try:
        store.create(plan, job_id="job-3")
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("Duplicate job ID was accepted")
