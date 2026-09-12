"""Deterministic Article -> Podcast workflow planning.

This module prepares an editable podcast production plan; it does not call an
LLM or generate audio. An eventual agent may replace the simple heuristics,
but the output contract remains stable and reviewable before execution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


@dataclass(slots=True)
class PodcastSegment:
    id: str
    speaker: str
    text: str
    direction: str | None = None
    chapter: str | None = None


@dataclass(slots=True)
class PodcastPlan:
    version: str
    title: str
    target_duration_minutes: float
    segments: list[PodcastSegment] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "title": self.title,
            "target_duration_minutes": self.target_duration_minutes,
            "segments": [
                {
                    "id": s.id,
                    "speaker": s.speaker,
                    "text": s.text,
                    "direction": s.direction,
                    "chapter": s.chapter,
                }
                for s in self.segments
            ],
            "assumptions": self.assumptions,
            "warnings": self.warnings,
        }


class ArticlePodcastPlanner:
    """Turn source prose into a deterministic, editable podcast outline."""

    def plan(
        self,
        article: str,
        *,
        title: str = "Untitled Podcast",
        target_duration_minutes: float = 10.0,
        narrator: str = "narrator",
        chunk_words: int = 120,
    ) -> PodcastPlan:
        text = re.sub(r"\s+", " ", (article or "").strip())
        if not text:
            raise ValueError("Article text cannot be empty.")
        if target_duration_minutes <= 0:
            raise ValueError("Target duration must be greater than zero.")
        if chunk_words < 20:
            raise ValueError("chunk_words must be at least 20.")

        words = text.split()
        chunks: list[str] = []
        for start in range(0, len(words), chunk_words):
            chunks.append(" ".join(words[start : start + chunk_words]))

        segments = [
            PodcastSegment(
                id=f"segment-{index:03d}",
                speaker=narrator,
                text=chunk,
                direction="clear, conversational podcast narration",
            )
            for index, chunk in enumerate(chunks, start=1)
        ]

        estimated_minutes = len(words) / 150.0
        warnings: list[str] = []
        if abs(estimated_minutes - target_duration_minutes) > max(1.0, target_duration_minutes * 0.25):
            warnings.append(
                f"Source length estimates about {estimated_minutes:.1f} minutes at 150 words/minute; "
                f"target is {target_duration_minutes:.1f} minutes."
            )

        return PodcastPlan(
            version="1",
            title=title.strip() or "Untitled Podcast",
            target_duration_minutes=float(target_duration_minutes),
            segments=segments,
            assumptions=[
                "One narrator is used until multi-speaker casting is requested.",
                "Source prose is preserved; editorial rewriting is not performed by this planner.",
                "Audio generation remains delegated to MaxxVoice/VoiceStudio capabilities.",
            ],
            warnings=warnings,
        )
