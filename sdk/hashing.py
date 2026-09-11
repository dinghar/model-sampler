"""Deterministic, language-portable bucketing.

Uses SHA-256 rather than a language built-in hash (e.g. Python's `hash()`)
because built-ins are not guaranteed stable across processes, versions, or
languages -- and this system needs the same (call_site_id, scope_id, salt)
to always produce the same bucket, everywhere, forever (until salt changes).
"""
import hashlib

TWO_POW_64 = 2 ** 64


def bucket_fraction(call_site_id: str, scope_id: str, salt: str) -> float:
    """Map (call_site_id, scope_id, salt) to a deterministic float in [0, 1)."""
    key = f"{call_site_id}:{scope_id}:{salt}".encode("utf-8")
    digest = hashlib.sha256(key).digest()
    as_int = int.from_bytes(digest[:8], byteorder="big")
    return as_int / TWO_POW_64


def assign_tier(call_site_id: str, scope_id: str, salt: str, sample_rate: float) -> str:
    """Pure hash-based tier assignment. Does not consult or persist any state --
    callers needing salt-rotation safety (bucket_assignments as source of truth)
    should use SmartSamplerClient.get_tier, not this function, directly."""
    if not (0.0 <= sample_rate <= 1.0):
        raise ValueError(f"sample_rate must be in [0, 1], got {sample_rate}")
    return "weak" if bucket_fraction(call_site_id, scope_id, salt) < sample_rate else "control"
