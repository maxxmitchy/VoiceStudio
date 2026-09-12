"""Execution planning primitives for Article -> Podcast rendering.

This module deliberately owns orchestration, not a second audio engine. It
converts an editable PodcastPlan into explicit synthesis requests and combines
returned segment artifacts into a reviewable render result. Actual audio
encoding remains the responsibility of the existing VoiceStudio capability
boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from maxxvoice.capabilities import SynthesisRequest, VoiceCapabilityService
from maxxvoice.workflows.article_podcast import PodcastPlan


@dataclass(slots=True)
class PodcastRenderResult:
    title: str
    status: str
    segments: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "status": self.status,
            "segments": self.segments,
            "warnings": self.warnings,
            "errors": self.errors,
        }


class ArticlePodcastRenderer:
    """Synthesize podcast segments through the stable MaxxVoice capability API."""

    def __init__(self, capabilities: VoiceCapabilityService | None = None):
        self.capabilities = capabilities or VoiceCapabilityService()

    async def render(
        self,
        plan: PodcastPlan,
        *,
        language: str | None = None,
        voice: str | None = None,
        reference_audio: str | None = None,
        synthesis_options: dict[str, Any] | None = None,
    ) -> PodcastRenderResult:
        result = PodcastRenderResult(
            title=plan.title,
            status="completed",
            warnings=list(plan.warnings),
        )

        for segment in plan.segments:
            try:
                artifact = await self.capabilities.synthesize(
                    SynthesisRequest(
                        text=segment.text,
                        language=language,
                        voice=voice or segment.speaker,
                        reference_audio=reference_audio,
                        direction=segment.direction,
                        options=dict(synthesis_options or {}),
                    )
                )
                result.segments.append(
                    {
                        "id": segment.id,
                        "speaker": segment.speaker,
                        "artifact": artifact,
                    }
                )
            except Exception as exc:  # noqa: BLE001 — workflow boundary
                result.status = "failed"
                result.errors.append(
                    f"Segment '{segment.id}' failed: {exc}"
                )
                break

        return result
