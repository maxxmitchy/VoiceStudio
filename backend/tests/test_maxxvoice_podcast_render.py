import pytest
import torch

from maxxvoice.workflows.article_podcast import ArticlePodcastPlanner
from maxxvoice.workflows.podcast_render import ArticlePodcastRenderer


class FakeCapabilities:
    async def synthesize(self, request):
        return {
            "audio": torch.ones(1, 100, dtype=torch.float32),
            "sample_rate": 1000,
            "engine_id": "fake-tts",
        }


@pytest.mark.asyncio
async def test_renderer_synthesizes_and_assembles_every_segment():
    plan = ArticlePodcastPlanner().plan(
        "One two three four five six seven eight nine ten eleven twelve.",
        chunk_words=5,
    )

    result = await ArticlePodcastRenderer(FakeCapabilities()).render(
        plan,
        language="en",
        voice="narrator",
    )

    assert result.status == "completed"
    assert len(result.segments) == 3
    assert result.segments[0]["speaker"] == "narrator"
    assert result.segments[0]["artifact"]["engine_id"] == "fake-tts"
    assert result.audio.shape == (1, 300)
    assert result.duration_seconds == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_renderer_stops_at_first_failed_segment():
    class FailingCapabilities:
        calls = 0

        async def synthesize(self, request):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("synthetic failure")
            return {
                "audio": torch.ones(1, 100, dtype=torch.float32),
                "sample_rate": 1000,
            }

    plan = ArticlePodcastPlanner().plan(
        "One two three four five six seven eight nine ten eleven twelve.",
        chunk_words=5,
    )

    result = await ArticlePodcastRenderer(FailingCapabilities()).render(plan)

    assert result.status == "failed"
    assert len(result.segments) == 1
    assert result.audio is None
    assert "segment-002" in result.errors[0]


@pytest.mark.asyncio
async def test_renderer_rejects_sample_rate_mismatch():
    class MixedRateCapabilities:
        calls = 0

        async def synthesize(self, request):
            self.calls += 1
            return {
                "audio": torch.ones(1, 100, dtype=torch.float32),
                "sample_rate": 1000 if self.calls == 1 else 2000,
            }

    plan = ArticlePodcastPlanner().plan(
        "One two three four five six seven eight nine ten eleven twelve.",
        chunk_words=5,
    )
    result = await ArticlePodcastRenderer(MixedRateCapabilities()).render(plan)

    assert result.status == "failed"
    assert "Sample-rate mismatch" in result.errors[0]
