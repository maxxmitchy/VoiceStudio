"""Unit tests for the MaxxVoice capability boundary.

These tests intentionally avoid loading speech models or optional engine
packages. They verify the contract layer is safe to import and that invalid
requests fail before touching heavyweight infrastructure.
"""

import pytest

from maxxvoice.capabilities import (
    CapabilityError,
    SynthesisRequest,
    TranscriptionRequest,
    VoiceCapabilityService,
)


def test_capability_catalogue_is_stable():
    payload = VoiceCapabilityService.capabilities()

    assert payload["version"] == "1"
    assert payload["implemented"] == ["synthesize", "transcribe"]
    assert payload["planned"] == ["clone_voice", "design_voice", "dub", "render"]
    assert payload["capabilities"] == [
        "synthesize",
        "transcribe",
        "clone_voice",
        "design_voice",
        "dub",
        "render",
    ]


@pytest.mark.asyncio
async def test_empty_synthesis_is_rejected_before_engine_resolution():
    service = VoiceCapabilityService()

    with pytest.raises(CapabilityError, match="non-empty text"):
        await service.synthesize(SynthesisRequest(text="   "))


@pytest.mark.asyncio
async def test_non_positive_speed_is_rejected_before_engine_resolution():
    service = VoiceCapabilityService()

    with pytest.raises(CapabilityError, match="greater than zero"):
        await service.synthesize(SynthesisRequest(text="hello", speed=0))


def test_empty_transcription_path_is_rejected_before_engine_resolution():
    service = VoiceCapabilityService()

    with pytest.raises(CapabilityError, match="audio path"):
        service.transcribe(TranscriptionRequest(audio_path=""))
