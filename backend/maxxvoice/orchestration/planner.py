"""Deterministic first-pass planner for MaxxVoice.

The planner turns a high-level request into a small, inspectable execution plan.
It deliberately does NOT call an LLM or execute jobs. That separation lets the
UI/API show the user what MaxxVoice intends to do before expensive work starts.
A future LLM planner can implement the same Plan contract without changing the
execution layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


@dataclass(slots=True)
class PlanStep:
    id: str
    capability: str
    purpose: str
    inputs: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Plan:
    version: str
    goal: str
    steps: list[PlanStep]
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "goal": self.goal,
            "steps": [
                {"id": s.id, "capability": s.capability, "purpose": s.purpose, "inputs": s.inputs}
                for s in self.steps
            ],
            "assumptions": self.assumptions,
            "warnings": self.warnings,
        }


class MaxxVoicePlanner:
    """Build a conservative plan from natural-language intent.

    Supported intent hints in this foundation:
      * audio/voice/text-to-speech → synthesize
      * transcribe/dictate/transcription → transcribe
      * clone voice → synthesize with a reference voice
      * design voice/create a voice → synthesize with a voice description
      * dub → transcribe + synthesize (execution composition comes later)

    Unknown requests are not guessed into an expensive workflow. They produce
    a plan with an explicit warning instead.
    """

    _TRANSCRIBE = re.compile(r"\b(transcrib|transcription|dictat|speech[- ]to[- ]text)\b", re.I)
    _DUB = re.compile(r"\b(dub|dubbing|translate .* (?:voice|audio|video))\b", re.I)
    _CLONE = re.compile(r"\b(clone|cloning|copy)\b.*\bvoice\b|\bvoice\b.*\b(clone|cloning|copy)\b", re.I)
    _DESIGN = re.compile(r"\b(design|create|generate)\b.*\bvoice\b", re.I)
    _SYNTH = re.compile(r"\b(synthesi[sz]|tts|text[- ]to[- ]speech|read .* aloud|narrat|voice[- ]over|podcast)\b", re.I)

    def plan(self, goal: str, *, context: dict[str, Any] | None = None) -> Plan:
        goal = (goal or "").strip()
        if not goal:
            raise ValueError("MaxxVoice planning requires a non-empty goal.")

        context = dict(context or {})
        steps: list[PlanStep] = []
        assumptions: list[str] = []
        warnings: list[str] = []

        if self._DUB.search(goal):
            steps.append(PlanStep("transcribe", "transcribe", "Extract the source speech and timing."))
            steps.append(PlanStep("synthesize", "synthesize", "Generate the translated/directed speech."))
            warnings.append("Dubbing execution and media replacement are not yet implemented in the MaxxVoice layer.")
        elif self._TRANSCRIBE.search(goal):
            steps.append(PlanStep("transcribe", "transcribe", "Convert source audio to timestamped text."))
        elif self._CLONE.search(goal):
            steps.append(PlanStep("synthesize", "synthesize", "Generate speech using a reference voice."))
            assumptions.append("A reference audio clip will be supplied by the caller.")
        elif self._DESIGN.search(goal) or self._SYNTH.search(goal):
            steps.append(PlanStep("synthesize", "synthesize", "Generate speech using the requested voice direction."))
        else:
            warnings.append("No supported speech intent was confidently detected; no expensive operation was selected.")

        if context:
            assumptions.append("Caller context is available to later execution stages.")

        return Plan(
            version="1",
            goal=goal,
            steps=steps,
            assumptions=assumptions,
            warnings=warnings,
        )
