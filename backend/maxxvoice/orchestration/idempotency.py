"""Helpers for safe, deterministic MaxxVoice workflow request identity."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_request_fingerprint(payload: dict[str, Any]) -> str:
    """Return a stable SHA-256 fingerprint for a JSON-compatible request."""
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_idempotency_key(key: str | None) -> str | None:
    """Normalize an optional client key without inventing one."""
    if key is None:
        return None
    normalized = key.strip()
    return normalized or None
