"""MaxxVoice capability layer.

This package is intentionally thin: VoiceStudio remains the speech/media
engine room; MaxxVoice provides stable, product-facing capability contracts
on top of the existing engine registries.
"""

from .capabilities import (
    CapabilityError,
    SynthesisRequest,
    TranscriptionRequest,
    VoiceCapabilityService,
)

__all__ = [
    "CapabilityError",
    "SynthesisRequest",
    "TranscriptionRequest",
    "VoiceCapabilityService",
]
