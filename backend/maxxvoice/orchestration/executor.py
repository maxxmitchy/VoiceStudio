"""Safe execution boundary for MaxxVoice plans.

The executor consumes an already-approved Plan and dispatches only capabilities
that are explicitly implemented. It never guesses missing inputs and never
falls back to an engine directly. This keeps planning and execution separate
and makes future job queues/agents interchangeable with this synchronous core.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from maxxvoice.capabilities import (
    CapabilityError,
    SynthesisRequest,
    TranscriptionRequest,
    VoiceCapabilityService,
)
from maxxvoice.orchestration.planner import Plan, PlanStep


class ExecutionError(RuntimeError):
    """Actionable failure raised while executing a MaxxVoice plan."""


@dataclass(slots=True)
class ExecutionResult:
    version: str
    goal: str
    status: str
    completed_steps: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "goal": self.goal,
            "status": self.status,
            "completed_steps": self.completed_steps,
            "artifacts": self.artifacts,
            "errors": self.errors,
        }


class MaxxVoiceExecutor:
    """Execute the safe subset of a MaxxVoice plan.

    Required inputs are supplied through ``context``. The executor intentionally
    does not infer filesystem paths, download models, or fabricate voice/audio
    inputs. A missing input stops the affected step with an actionable error.
    """

    def __init__(self, capabilities: VoiceCapabilityService | None = None):
        self.capabilities = capabilities or VoiceCapabilityService()

    async def execute(self, plan: Plan, *, context: dict[str, Any] | None = None) -> ExecutionResult:
        context = dict(context or {})
        result = ExecutionResult(version=plan.version, goal=plan.goal, status="completed")

        for step in plan.steps:
            try:
                artifact = await self._execute_step(step, context, result.artifacts)
            except (CapabilityError, ExecutionError) as exc:
                result.status = "failed"
                result.errors.append(str(exc))
                break
            except Exception as exc:  # noqa: BLE001 — normalize product boundary
                result.status = "failed"
                result.errors.append(f"Step '{step.id}' failed: {exc}")
                break

            result.completed_steps.append(step.id)
            result.artifacts[step.id] = artifact

        if not plan.steps and plan.warnings:
            result.status = "not_executable"
            result.errors.extend(plan.warnings)

        return result

    async def _execute_step(
        self,
        step: PlanStep,
        context: dict[str, Any],
        artifacts: dict[str, Any],
    ) -> Any:
        if step.capability == "transcribe":
            audio_path = context.get("audio_path") or context.get("source_audio")
            if not audio_path:
                raise ExecutionError(
                    "Transcription requires context.audio_path (or context.source_audio)."
                )
            return await _maybe_await(
                self.capabilities.transcribe(
                    TranscriptionRequest(
                        audio_path=str(audio_path),
                        language=context.get("language"),
                        word_timestamps=bool(context.get("word_timestamps", True)),
                    )
                )
            )

        if step.capability == "synthesize":
            text = context.get("text") or context.get("script")
            # A transcription step may supply the source text for a later
            # synthesis step. Keep the mapping explicit rather than magical.
            if not text and "transcribe" in artifacts:
                text = artifacts["transcribe"].get("text")
            if not text:
                raise ExecutionError(
                    "Synthesis requires context.text (or context.script), or a prior transcription artifact."
                )

            return await self.capabilities.synthesize(
                SynthesisRequest(
                    text=str(text),
                    language=context.get("target_language") or context.get("language"),
                    voice=context.get("voice"),
                    reference_audio=context.get("reference_audio"),
                    reference_text=context.get("reference_text"),
                    voice_description=context.get("voice_description"),
                    direction=context.get("direction"),
                    speed=float(context.get("speed", 1.0)),
                    duration=context.get("duration"),
                    num_steps=int(context.get("num_steps", 16)),
                    guidance_scale=float(context.get("guidance_scale", 2.0)),
                    options=dict(context.get("synthesis_options") or {}),
                )
            )

        raise ExecutionError(
            f"Capability '{step.capability}' is not executable in MaxxVoice v1."
        )


async def _maybe_await(value: Any) -> Any:
    """Accept sync capability implementations while the boundary is async."""
    return value
