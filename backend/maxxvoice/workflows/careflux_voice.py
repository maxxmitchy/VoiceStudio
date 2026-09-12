"""Careflux/WelLivox presentation-voice workflow.

This boundary is intentionally presentation-only: callers provide already
approved, display-safe text. MaxxVoice does not perform clinical reasoning,
patient-data selection, or treatment decisions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from maxxvoice.capabilities import VoiceCapabilityService
from services.audio_io import atomic_save_wav


@dataclass
class CarefluxVoiceResult:
    status: str
    artifact: dict[str, Any]
    engine_id: Optional[str] = None
    model_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "artifact": self.artifact,
            "engine_id": self.engine_id,
            "model_id": self.model_id,
        }


class CarefluxVoiceRenderer:
    """Render one approved Careflux message using the existing TTS registry."""

    def __init__(self, capability_service: VoiceCapabilityService | None = None) -> None:
        self.capability_service = capability_service or VoiceCapabilityService()

    async def render(
        self,
        text: str,
        *,
        language: str | None = None,
        voice: str | None = None,
        direction: str | None = None,
        reference_audio: str | None = None,
        synthesis_options: dict[str, Any] | None = None,
        artifact_path: str | None = None,
    ) -> CarefluxVoiceResult:
        text = text.strip()
        if not text:
            raise ValueError("text must not be empty")

        result = await self.capability_service.synthesize(
            text=text,
            language=language,
            voice=voice,
            reference_audio=reference_audio,
            direction=direction or "clear, warm, professional Nigerian healthcare voice",
            options=synthesis_options or {},
        )
        audio = result["audio"]
        sample_rate = int(result["sample_rate"])

        artifact = {
            "type": "audio/wav",
            "sample_rate": sample_rate,
            "engine_id": result.get("engine_id"),
            "model_id": result.get("model_id"),
        }
        if artifact_path:
            atomic_save_wav(artifact_path, audio, sample_rate)
            artifact["path"] = artifact_path

        return CarefluxVoiceResult(
            status="completed",
            artifact=artifact,
            engine_id=result.get("engine_id"),
            model_id=result.get("model_id"),
        )
