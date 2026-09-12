"""Stable product-facing speech capabilities for MaxxVoice.

The key design rule is adapter ownership: this module never imports or selects
individual TTS/ASR model implementations. It resolves through VoiceStudio's
existing registries, so new engines remain replaceable and upstream workflow
behaviour is preserved.

This first capability slice deliberately covers synthesis and transcription.
Higher-level operations (clone, design, dubbing and render) should compose these
contracts rather than create a second engine-selection system.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


class CapabilityError(RuntimeError):
    """Actionable failure raised by the MaxxVoice capability boundary."""


@dataclass(slots=True)
class SynthesisRequest:
    text: str
    language: Optional[str] = None
    voice: Optional[str] = None
    reference_audio: Optional[str] = None
    reference_text: Optional[str] = None
    voice_description: Optional[str] = None
    direction: Optional[str] = None
    speed: float = 1.0
    duration: Optional[float] = None
    num_steps: int = 16
    guidance_scale: float = 2.0
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TranscriptionRequest:
    audio_path: str
    language: Optional[str] = None
    word_timestamps: bool = True


class VoiceCapabilityService:
    """Resolve and execute VoiceStudio speech capabilities.

    Instances are cheap and stateless. Engine lifecycle, model caching,
    hardware routing and availability remain owned by the existing services.
    """

    async def synthesize(self, request: SynthesisRequest):
        """Generate one utterance through the active TTS backend."""
        text = (request.text or "").strip()
        if not text:
            raise CapabilityError("Synthesis requires non-empty text.")
        if request.speed <= 0:
            raise CapabilityError("Synthesis speed must be greater than zero.")

        from services.tts_backend import resolve_generation_backend

        try:
            backend = await resolve_generation_backend(
                require_cloning=bool(request.reference_audio),
                cloning_purpose="voice synthesis",
            )
            kwargs: dict[str, Any] = {
                "language": request.language,
                "ref_audio": request.reference_audio,
                "ref_text": request.reference_text,
                "description": request.voice_description,
                "instruct": request.direction,
                "speed": request.speed,
                "duration": request.duration,
                "num_step": request.num_steps,
                "guidance_scale": request.guidance_scale,
            }
            if request.voice:
                kwargs["voice"] = request.voice
            kwargs.update(request.options)
            audio = backend.generate(text, **kwargs)
        except (ValueError, CapabilityError):
            raise
        except Exception as exc:  # noqa: BLE001 — preserve one product boundary
            raise CapabilityError(
                f"Synthesis failed using TTS engine '{getattr(backend, 'id', 'unknown')}': {exc}"
            ) from exc

        return {
            "audio": audio,
            "sample_rate": backend.sample_rate,
            "engine_id": backend.id,
            "model_id": backend.model_identity(),
        }

    def transcribe(self, request: TranscriptionRequest) -> dict[str, Any]:
        """Transcribe one audio file through the active ASR backend."""
        if not (request.audio_path or "").strip():
            raise CapabilityError("Transcription requires an audio path.")

        from services.asr_backend import load_active_asr_backend

        try:
            backend = load_active_asr_backend()
            result = backend.transcribe(
                request.audio_path,
                word_timestamps=request.word_timestamps,
                **({"language": request.language} if request.language else {}),
            )
        except (ValueError, CapabilityError):
            raise
        except Exception as exc:  # noqa: BLE001 — preserve one product boundary
            raise CapabilityError(
                f"Transcription failed using ASR engine '{getattr(backend, 'id', 'unknown')}': {exc}"
            ) from exc

        result = dict(result or {})
        result.setdefault("text", "")
        result.setdefault("chunks", [])
        result.setdefault("segments", [])
        result["engine_id"] = backend.id
        result["model_id"] = backend.model_identity() if hasattr(backend, "model_identity") else None
        return result

    @staticmethod
    def capabilities() -> dict[str, Any]:
        """Return the stable capability vocabulary exposed to product layers."""
        return {
            "version": "1",
            "capabilities": [
                "synthesize",
                "transcribe",
                "clone_voice",
                "design_voice",
                "dub",
                "render",
            ],
            "implemented": ["synthesize", "transcribe"],
            "planned": ["clone_voice", "design_voice", "dub", "render"],
        }
