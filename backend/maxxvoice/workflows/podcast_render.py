"""Article -> Podcast synthesis, assembly and quality checks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from maxxvoice.capabilities import SynthesisRequest, VoiceCapabilityService
from maxxvoice.workflows.article_podcast import PodcastPlan


class SegmentCheckpointStore(Protocol):
    """Minimal checkpoint contract; persistence remains outside the renderer."""

    def mark_running(self, job_id: str, step_id: str) -> Any: ...

    def mark_completed(
        self, job_id: str, step_id: str, artifact: dict[str, Any] | None = None
    ) -> Any: ...

    def mark_failed(self, job_id: str, step_id: str, error: str) -> Any: ...


@dataclass(slots=True)
class PodcastRenderResult:
    title: str
    status: str
    duration_seconds: float = 0.0
    sample_rate: int | None = None
    output_path: str | None = None
    audio: Any = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "sample_rate": self.sample_rate,
            "output_path": self.output_path,
            "segments": [
                {k: v for k, v in item.items() if k != "artifact"}
                for item in self.segments
            ],
            "warnings": self.warnings,
            "errors": self.errors,
        }


class ArticlePodcastRenderer:
    """Execute an ArticlePodcast plan through MaxxVoice's synthesis boundary."""

    def __init__(self, capabilities: VoiceCapabilityService | None = None):
        self.capabilities = capabilities or VoiceCapabilityService()

    @staticmethod
    def _assemble(audio_parts: list[Any]) -> Any:
        """Concatenate engine waveforms without introducing another audio engine."""
        import torch

        if not audio_parts:
            return torch.zeros(0, dtype=torch.float32)
        normalized = []
        for audio in audio_parts:
            if not torch.is_tensor(audio) or audio.numel() == 0:
                raise ValueError("Synthesis returned an empty or invalid audio tensor.")
            if audio.ndim == 1:
                audio = audio.unsqueeze(0)
            if audio.ndim != 2:
                raise ValueError(f"Audio tensor must be 1D or 2D, got {audio.ndim}D.")
            normalized.append(audio.detach())

        channels = normalized[0].shape[0]
        dtype = normalized[0].dtype
        device = normalized[0].device
        for audio in normalized[1:]:
            if audio.shape[0] != channels:
                raise ValueError("Podcast segments have incompatible channel counts.")
        return torch.cat(
            [a.to(device=device, dtype=dtype).contiguous() for a in normalized],
            dim=-1,
        )

    async def render(
        self,
        plan: PodcastPlan,
        *,
        language: str | None = None,
        voice: str | None = None,
        reference_audio: str | None = None,
        synthesis_options: dict[str, Any] | None = None,
        output_path: str | None = None,
        checkpoint_store: SegmentCheckpointStore | None = None,
        job_id: str | None = None,
    ) -> PodcastRenderResult:
        """Synthesize, checkpoint, assemble, QC and optionally publish a WAV artifact.

        Checkpoints record durable segment lifecycle state but do not yet imply
        automatic resume: completed audio is only reusable once its artifact has
        been persisted and independently validated by a recovery path.
        """
        result = PodcastRenderResult(
            title=plan.title,
            status="completed",
            warnings=list(plan.warnings),
        )
        audio_parts: list[Any] = []

        for segment in plan.segments:
            if checkpoint_store and job_id:
                checkpoint_store.mark_running(job_id, segment.id)
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
                audio = artifact.get("audio") if isinstance(artifact, dict) else None
                sample_rate = artifact.get("sample_rate") if isinstance(artifact, dict) else None
                if audio is None or not sample_rate:
                    raise ValueError("Synthesis returned no audio or sample rate.")
                if result.sample_rate is None:
                    result.sample_rate = int(sample_rate)
                elif int(sample_rate) != result.sample_rate:
                    raise ValueError(
                        f"Sample-rate mismatch: expected {result.sample_rate}, got {sample_rate}."
                    )
                segment_info = {
                    "id": segment.id,
                    "speaker": segment.speaker,
                    "sample_rate": int(sample_rate),
                    "samples": int(audio.shape[-1]),
                    "artifact": artifact,
                }
                audio_parts.append(audio)
                result.segments.append(segment_info)
                if checkpoint_store and job_id:
                    checkpoint_store.mark_completed(
                        job_id,
                        segment.id,
                        {
                            "speaker": segment.speaker,
                            "sample_rate": int(sample_rate),
                            "samples": int(audio.shape[-1]),
                            "engine_id": artifact.get("engine_id") if isinstance(artifact, dict) else None,
                            "model_id": artifact.get("model_id") if isinstance(artifact, dict) else None,
                        },
                    )
            except Exception as exc:  # noqa: BLE001 — workflow boundary
                if checkpoint_store and job_id:
                    checkpoint_store.mark_failed(job_id, segment.id, str(exc))
                result.status = "failed"
                result.errors.append(f"Segment '{segment.id}' failed: {exc}")
                break

        if result.status == "failed":
            return result

        try:
            result.audio = self._assemble(audio_parts)
            if result.audio.numel() == 0:
                result.status = "failed"
                result.errors.append("Podcast render produced no audio.")
                return result
            result.duration_seconds = result.audio.shape[-1] / float(result.sample_rate)
            if plan.target_duration_minutes > 0:
                target = plan.target_duration_minutes * 60.0
                if abs(result.duration_seconds - target) > max(60.0, target * 0.25):
                    result.warnings.append(
                        f"Rendered duration is {result.duration_seconds / 60:.1f} minutes; "
                        f"target is {plan.target_duration_minutes:.1f} minutes."
                    )
            if output_path:
                from services.audio_io import atomic_save_wav
                atomic_save_wav(output_path, result.audio, result.sample_rate)
                result.output_path = output_path
        except Exception as exc:  # noqa: BLE001 — finalization boundary
            result.status = "failed"
            result.errors.append(f"Podcast assembly/export failed: {exc}")

        return result
