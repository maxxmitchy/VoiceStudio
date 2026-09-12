"""Minimal MaxxVoice HTTP boundary.

This router exposes planning/status only in the first orchestration milestone.
It is intentionally side-effect free: POST /maxxvoice/plan never downloads a
model, starts a worker, or generates audio.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from maxxvoice.capabilities import VoiceCapabilityService
from maxxvoice.orchestration import MaxxVoicePlanner

router = APIRouter(prefix="/maxxvoice", tags=["maxxvoice"])


class PlanRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=10_000)
    context: dict = Field(default_factory=dict)


@router.get("/status")
def status():
    return {
        "name": "MaxxVoice",
        "version": "1",
        "mode": "orchestration-foundation",
        "capabilities": VoiceCapabilityService.capabilities(),
    }


@router.post("/plan")
def plan(request: PlanRequest):
    return MaxxVoicePlanner().plan(request.goal, context=request.context).to_dict()
