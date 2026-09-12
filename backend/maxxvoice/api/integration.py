"""Application integration boundary for MaxxVoice.

This module deliberately keeps VoiceStudio's bootstrap concerns out of the
MaxxVoice package. The host FastAPI application can mount the MaxxVoice router
with one small, explicit call without importing individual voice engines.
"""

from __future__ import annotations

from typing import Any


def mount_maxxvoice(app: Any) -> None:
    """Mount the MaxxVoice API router on an existing FastAPI application.

    The import is intentionally lazy so importing the integration helper does
    not make FastAPI startup depend on MaxxVoice's heavier dependencies.
    """
    from .router import router

    app.include_router(router)
