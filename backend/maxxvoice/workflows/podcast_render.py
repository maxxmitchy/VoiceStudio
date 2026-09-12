"""Article -> Podcast synthesis, assembly and quality checks."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from maxxvoice.capabilities import SynthesisRequest, VoiceCapabilityService
from maxxvoice.workflows.article_podcast import PodcastPlan


class SegmentCheckpointStore(Protocol):
    """Minimal durable checkpoint contract used by the renderer."""

    def get(self, job_id: str, step_id: str) -> Any: ...
    def mark_running(self, job_id: str, step_id: str) -> Any: ...
    def mark_completed(self, job_id: str, step_id: str, artifact: dict[str, Any] | None = None) -> Any: ...
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
            "segments": [{k: v for k, v in item.items() if k != "artifact"} for item in self.segments],
            "warnings": self.warnings,
            "errors": self.errors,
        }


class ArticlePodcastRenderer:
    """Execute an ArticlePodcast plan through MaxxVoice's synthesis boundary."""

    def __init__(self, capabilities: VoiceCapabilityService | None = None):
        self.capabilities = capabilities or VoiceCapabilityService()

    @staticmethod
    def _assemble(audio_parts: list[Any]) -> Any:
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
        dtype, device = normalized[0].dtype, normalized[0].device
        if any(audio.shape[0] != channels for audio in normalized[1:]):
            raise ValueError("Podcast segments have incompatible channel counts.")
        return torch.cat([a.to(device=device, dtype=dtype).contiguous() for a in normalized], dim=-1)

    @staticmethod
    def _segment_path(job_id: str, segment_id: str, artifact_dir: str | Path | None) -> Path:
        root = Path(artifact_dir or ".data/maxxvoice_artifacts")
        return root / job_id / f"{segment_id}.wav"

    @staticmethod
    def _persist_and_validate(path: Path, audio: Any, sample_rate: int) -> dict[str, Any]:
        """Atomically publish a segment and independently verify the resulting WAV."""
        from services.audio_io import atomic_save_wav
        import soundfile as sf

        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_save_wav(str(path), audio, sample_rate)
        info = sf.info(str(path))
        if info.frames <= 0 or info.samplerate != int(sample_rate) or info.channels <= 0:
            raise ValueError("Persisted segment artifact failed validation.")
        return {
            "path": str(path),
            "format": "wav",
            "sample_rate": int(info.samplerate),
            "samples": int(info.frames),
            "channels": int(info.channels),
            "size_bytes": path.stat().st_size,
        }

    @staticmethod
    def _load_validated(path: Path, expected_sample_rate: int | None = None) -> tuple[Any, int] | None:
        if not path.is_file() or path.stat().st_size <= 44:
            return None
        import soundfile as sf
        import torch
        try:
            data, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
            info = sf.info(str(path))
            if info.frames <= 0 or info.channels <= 0 or (expected_sample_rate and sample_rate != expected_sample_rate):
                return None
            audio = torch.from_numpy(data.T.copy())
            if audio.numel() == 0:
                return None
            return audio, int(sample_rate)
        except Exception:
            return None

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
        artifact_dir: str | Path | None = None,
    ) -> PodcastRenderResult:
        """Render while reusing only checkpoints whose WAV artifact validates."""
        result = PodcastRenderResult(title=plan.title, status="completed", warnings=list(plan.warnings))
        audio_parts: list[Any] = []

        for segment in plan.segments:
            checkpoint = checkpoint_store.get(job_id, segment.id) if checkpoint_store and job_id else None
            reused = False
            if checkpoint and checkpoint.status == "completed" and checkpoint.artifact:
                saved = checkpoint.artifact
                saved_path = Path(saved.get("path", ""))
                loaded = self._load_validated(saved_path, result.sample_rate)
                if loaded is not None:
                    audio, sample_rate = loaded
                    result.sample_rate = result.sample_rate or sample_rate
                    audio_parts.append(audio)
                    result.segments.append({"id": segment.id, "speaker": segment.speaker, "sample_rate": sample_rate, "samples": int(audio.shape[-1]), "artifact": saved, "resumed": True})
                    reused = True
            if reused:
                continue

            try:
                if checkpoint_store and job_id:
                    checkpoint_store.mark_running(job_id, segment.id)
                artifact = await self.capabilities.synthesize(SynthesisRequest(
                    text=segment.text,
                    language=language,
                    voice=voice or segment.speaker,
                    reference_audio=reference_audio,
                    direction=segment.direction,
                    options=dict(synthesis_options or {}),
                ))
                audio = artifact.get("audio") if isinstance(artifact, dict) else None
                sample_rate = artifact.get("sample_rate") if isinstance(artifact, dict) else None
                if audio is None or not sample_rate:
                    raise ValueError("Synthesis returned no audio or sample rate.")
                sample_rate = int(sample_rate)
                if result.sample_rate is None:
                    result.sample_rate = sample_rate
                elif sample_rate != result.sample_rate:
                    raise ValueError(f"Sample-rate mismatch: expected {result.sample_rate}, got {sample_rate}.")
                persisted = self._persist_and_validate(self._segment_path(job_id or "standalone", segment.id, artifact_dir), audio, sample_rate)
                checkpoint_artifact = {**persisted, "engine_id": artifact.get("engine_id") if isinstance(artifact, dict) else None, "model_id": artifact.get("model_id") if isinstance(artifact, dict) else None, "speaker": segment.speaker}
                if checkpoint_store and job_id:
                    checkpoint_store.mark_completed(job_id, segment.id, checkpoint_artifact)
                audio_parts.append(audio)
                result.segments.append({"id": segment.id, "speaker": segment.speaker, "sample_rate": sample_rate, "samples": int(audio.shape[-1]), "artifact": checkpoint_artifact})
            except Exception as exc:
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
                raise ValueError("Podcast render produced no audio.")
            result.duration_seconds = result.audio.shape[-1] / float(result.sample_rate)
            if plan.target_duration_minutes > 0:
                target = plan.target_duration_minutes * 60.0
                if abs(result.duration_seconds - target) > max(60.0, target * 0.25):
                    result.warnings.append(f"Rendered duration is {result.duration_seconds / 60:.1f} minutes; target is {plan.target_duration_minutes:.1f} minutes.")
            if output_path:
                from services.audio_io import atomic_save_wav
                atomic_save_wav(output_path, result.audio, result.sample_rate)
                result.output_path = output_path
        except Exception as exc:
            result.status = "failed"
            result.errors.append(f"Podcast assembly/export failed: {exc}")
        return result
