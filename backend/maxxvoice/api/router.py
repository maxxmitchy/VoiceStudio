"""MaxxVoice HTTP boundary.

The router exposes deterministic planning plus explicit Article -> Podcast
execution. Workflow execution is opt-in: planning never generates audio, while
rendering executes only the supplied article and synthesis parameters.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from maxxvoice.capabilities import VoiceCapabilityService
from maxxvoice.orchestration import MaxxVoicePlanner
from maxxvoice.workflows import ArticlePodcastPlanner, ArticlePodcastRenderer

router = APIRouter(prefix="/maxxvoice", tags=["maxxvoice"])


class PlanRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=10_000)
    context: dict = Field(default_factory=dict)


class ArticlePodcastRequest(BaseModel):
    article: str = Field(min_length=1, max_length=500_000)
    title: str = Field(default="Untitled Podcast", max_length=500)
    target_duration_minutes: float = Field(default=10.0, gt=0, le=240)
    narrator: str = Field(default="narrator", min_length=1, max_length=200)
    chunk_words: int = Field(default=120, ge=20, le=2_000)
    language: str | None = Field(default=None, max_length=50)
    voice: str | None = Field(default=None, max_length=200)
    reference_audio: str | None = Field(default=None, max_length=4_000)
    synthesis_options: dict = Field(default_factory=dict)


@router.get("/status")
def status():
    return {
        "name": "MaxxVoice",
        "version": "1",
        "mode": "orchestration-foundation",
        "capabilities": VoiceCapabilityService.capabilities(),
    }


@router.post("/plan")
def plan(request: PlanRequest):
    return MaxxVoicePlanner().plan(request.goal, context=request.context).to_dict()


@router.post("/workflows/article-podcast")
async def article_podcast(request: ArticlePodcastRequest):
    """Plan and render an article as a single-narrator podcast."""
    podcast_plan = ArticlePodcastPlanner().plan(
        request.article,
        title=request.title,
        target_duration_minutes=request.target_duration_minutes,
        narrator=request.narrator,
        chunk_words=request.chunk_words,
    )

    result = await ArticlePodcastRenderer().render(
        podcast_plan,
        language=request.language,
        voice=request.voice,
        reference_audio=request.reference_audio,
        synthesis_options=request.synthesis_options,
    )

    payload = result.to_dict()
    payload["plan"] = podcast_plan.to_dict()
    return payload
