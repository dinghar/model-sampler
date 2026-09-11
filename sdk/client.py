"""Thin HTTP client SDK that application code imports to route LLM calls
through the model-tier experiment and report outcomes.

Two layers, per the implementation plan:
  - sdk.hashing.assign_tier: pure, offline, no I/O.
  - SmartSamplerClient (this module): talks to the API service, which is the
    canonical source of truth for a scope's tier via bucket_assignments (so
    that rotating a call site's salt cannot flip a scope already in flight).
"""
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple, TypeVar

import httpx

from sdk.hashing import assign_tier as _compute_tier_locally

logger = logging.getLogger("smart_sampler_sdk")

T = TypeVar("T")


@dataclass(frozen=True)
class CallSiteConfig:
    call_site_id: str
    control_model: str
    weak_model: str
    sample_rate: float
    salt: str
    outcome_score_type: str
    scale_min: Optional[float]
    scale_max: Optional[float]
    scale_success_threshold: Optional[float]
    enabled: bool


class SmartSamplerClient:
    def __init__(
        self,
        api_base_url: str,
        config_ttl_seconds: float = 300.0,
        request_timeout_seconds: float = 5.0,
        http_client: Optional[httpx.Client] = None,
    ):
        self.api_base_url = api_base_url.rstrip("/")
        self.config_ttl_seconds = config_ttl_seconds
        self._http = http_client or httpx.Client(timeout=request_timeout_seconds)
        self._lock = threading.Lock()
        self._config_cache: Dict[str, Tuple[CallSiteConfig, float]] = {}
        self._tier_cache: Dict[Tuple[str, str], str] = {}

    def close(self):
        self._http.close()

    # -- config -------------------------------------------------------

    def _fetch_config(self, call_site_id: str) -> CallSiteConfig:
        resp = self._http.get(f"{self.api_base_url}/api/call-sites/{call_site_id}")
        resp.raise_for_status()
        data = resp.json()
        return CallSiteConfig(**{k: data[k] for k in CallSiteConfig.__dataclass_fields__})

    def get_config(self, call_site_id: str) -> CallSiteConfig:
        now = time.monotonic()
        with self._lock:
            cached = self._config_cache.get(call_site_id)
        if cached is not None and now - cached[1] < self.config_ttl_seconds:
            return cached[0]
        try:
            config = self._fetch_config(call_site_id)
        except httpx.HTTPError as exc:
            if cached is not None:
                logger.warning("config refresh failed for %s, using stale cache: %s", call_site_id, exc)
                return cached[0]
            raise RuntimeError(
                f"no cached config for call_site_id={call_site_id!r} and initial fetch failed"
            ) from exc
        with self._lock:
            self._config_cache[call_site_id] = (config, now)
        return config

    # -- tier assignment ------------------------------------------------

    def get_tier(self, call_site_id: str, scope_id: str) -> str:
        key = (call_site_id, scope_id)
        with self._lock:
            cached = self._tier_cache.get(key)
        if cached is not None:
            return cached

        try:
            resp = self._http.post(
                f"{self.api_base_url}/api/call-sites/{call_site_id}/assign",
                json={"scope_id": scope_id},
            )
            resp.raise_for_status()
            tier = resp.json()["tier"]
        except httpx.HTTPError as exc:
            logger.warning(
                "assign lookup failed for %s/%s, falling back to local hash: %s",
                call_site_id, scope_id, exc,
            )
            config = self.get_config(call_site_id)
            tier = (
                "control" if not config.enabled
                else _compute_tier_locally(call_site_id, scope_id, config.salt, config.sample_rate)
            )

        with self._lock:
            self._tier_cache[key] = tier
        return tier

    def get_model(self, call_site_id: str, scope_id: str) -> str:
        config = self.get_config(call_site_id)
        tier = self.get_tier(call_site_id, scope_id)
        return config.weak_model if tier == "weak" else config.control_model

    # -- telemetry --------------------------------------------------------

    def record_call(self, call_site_id: str, scope_id: str, model_used: str, tier: str,
                     request_id: Optional[str] = None) -> None:
        try:
            self._http.post(
                f"{self.api_base_url}/api/telemetry/call-events",
                json={
                    "call_site_id": call_site_id,
                    "scope_id": scope_id,
                    "model_used": model_used,
                    "tier": tier,
                    "request_id": request_id,
                },
            )
        except httpx.HTTPError as exc:
            logger.warning("failed to record call event for %s/%s: %s", call_site_id, scope_id, exc)

    def call(self, call_site_id: str, scope_id: str, invoke: Callable[[str], T],
              request_id: Optional[str] = None) -> T:
        """Resolve the model for this scope, invoke it, and record the call event."""
        config = self.get_config(call_site_id)
        tier = self.get_tier(call_site_id, scope_id)
        model = config.weak_model if tier == "weak" else config.control_model
        result = invoke(model)
        self.record_call(call_site_id, scope_id, model_used=model, tier=tier, request_id=request_id)
        return result

    def report_outcome(self, call_site_id: str, scope_id: str, score, source: Optional[str] = None) -> None:
        if isinstance(score, bool):
            score_type = "boolean"
            score = 1.0 if score else 0.0
        else:
            score_type = "scale"
            score = float(score)
        try:
            self._http.post(
                f"{self.api_base_url}/api/telemetry/outcome-events",
                json={
                    "call_site_id": call_site_id,
                    "scope_id": scope_id,
                    "score": score,
                    "score_type": score_type,
                    "source": source,
                },
            )
        except httpx.HTTPError as exc:
            logger.warning("failed to report outcome for %s/%s: %s", call_site_id, scope_id, exc)
