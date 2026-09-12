import pytest

from maxxvoice.orchestration import (
    InMemoryJobStore,
    JobStatus,
    MaxxVoiceExecutor,
    MaxxVoiceJobRunner,
    MaxxVoicePlanner,
    StepStatus,
)


class FakeCapabilities:
    async def synthesize(self, request):
        return {"audio": b"audio", "engine_id": "fake-tts"}

    def transcribe(self, request):
        return {"text": "hello world", "segments": []}


@pytest.mark.asyncio
async def test_runner_records_completed_workflow():
    plan = MaxxVoicePlanner().plan("Dub this recording")
    store = InMemoryJobStore()
    runner = MaxxVoiceJobRunner(
        store=store,
        executor=MaxxVoiceExecutor(FakeCapabilities()),
    )

    job = await runner.run(
        plan,
        context={"audio_path": "/tmp/source.wav", "target_language": "fr"},
        job_id="job-run-1",
    )

    assert job.status == JobStatus.FAILED
    assert job.steps[0].status == StepStatus.COMPLETED
    assert job.steps[1].status == StepStatus.COMPLETED
    assert job.completed_at is not None


@pytest.mark.asyncio
async def test_runner_records_failed_step():
    plan = MaxxVoicePlanner().plan("Transcribe this recording")
    runner = MaxxVoiceJobRunner(executor=MaxxVoiceExecutor(FakeCapabilities()))

    job = await runner.run(plan, job_id="job-run-2")

    assert job.status == JobStatus.FAILED
    assert job.steps[0].status == StepStatus.FAILED
    assert "context.audio_path" in job.steps[0].error
