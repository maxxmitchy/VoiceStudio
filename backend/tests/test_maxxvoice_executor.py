import pytest

from maxxvoice.capabilities import CapabilityError
from maxxvoice.orchestration import MaxxVoiceExecutor, MaxxVoicePlanner


class FakeCapabilities:
    def __init__(self):
        self.calls = []

    async def synthesize(self, request):
        self.calls.append(("synthesize", request))
        return {"audio": b"audio", "engine_id": "fake-tts"}

    def transcribe(self, request):
        self.calls.append(("transcribe", request))
        return {"text": "hello world", "segments": []}


@pytest.mark.asyncio
async def test_executor_runs_transcription_then_synthesis():
    planner = MaxxVoicePlanner()
    plan = planner.plan("Dub this recording")
    fake = FakeCapabilities()

    result = await MaxxVoiceExecutor(fake).execute(
        plan,
        context={"audio_path": "/tmp/source.wav", "target_language": "fr"},
    )

    assert result.status == "completed"
    assert result.completed_steps == ["transcribe", "synthesize"]
    assert [name for name, _ in fake.calls] == ["transcribe", "synthesize"]
    assert fake.calls[1][1].text == "hello world"
    assert fake.calls[1][1].language == "fr"


@pytest.mark.asyncio
async def test_executor_refuses_missing_transcription_input():
    plan = MaxxVoicePlanner().plan("Transcribe this recording")
    result = await MaxxVoiceExecutor(FakeCapabilities()).execute(plan)

    assert result.status == "failed"
    assert result.completed_steps == []
    assert "context.audio_path" in result.errors[0]


@pytest.mark.asyncio
async def test_executor_refuses_unknown_capability():
    from maxxvoice.orchestration.planner import Plan, PlanStep

    plan = Plan("1", "future workflow", [PlanStep("x", "future_capability", "test")])
    result = await MaxxVoiceExecutor(FakeCapabilities()).execute(plan)

    assert result.status == "failed"
    assert "future_capability" in result.errors[0]
