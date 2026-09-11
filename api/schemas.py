from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field, model_validator


class CallSiteConfigIn(BaseModel):
    call_site_id: str
    control_model: str
    weak_model: str
    sample_rate: float = Field(ge=0.0, le=1.0)
    salt: str
    outcome_score_type: Literal["boolean", "scale"]
    scale_min: Optional[float] = None
    scale_max: Optional[float] = None
    scale_success_threshold: Optional[float] = None
    enabled: bool = True

    @model_validator(mode="after")
    def check_models_distinct_and_scale_bounds(self):
        if self.control_model == self.weak_model:
            raise ValueError("control_model and weak_model must differ")
        if self.outcome_score_type == "scale":
            if self.scale_min is None or self.scale_max is None:
                raise ValueError("scale_min and scale_max are required when outcome_score_type is 'scale'")
            if self.scale_max <= self.scale_min:
                raise ValueError("scale_max must be greater than scale_min")
        return self


class CallSiteConfigPatch(BaseModel):
    control_model: Optional[str] = None
    weak_model: Optional[str] = None
    sample_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    salt: Optional[str] = None
    outcome_score_type: Optional[Literal["boolean", "scale"]] = None
    scale_min: Optional[float] = None
    scale_max: Optional[float] = None
    scale_success_threshold: Optional[float] = None
    enabled: Optional[bool] = None
    changed_by: Optional[str] = None


class CallSiteConfigOut(BaseModel):
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

    class Config:
        from_attributes = True


class AssignRequest(BaseModel):
    scope_id: str


class AssignResponse(BaseModel):
    call_site_id: str
    scope_id: str
    tier: Literal["control", "weak"]
    model: str


class CallEventIn(BaseModel):
    call_site_id: str
    scope_id: str
    model_used: str
    tier: Literal["control", "weak"]
    request_id: Optional[str] = None
    occurred_at: Optional[datetime] = None


class OutcomeEventIn(BaseModel):
    call_site_id: str
    scope_id: str
    score: float
    score_type: Literal["boolean", "scale"]
    source: Optional[str] = None
    occurred_at: Optional[datetime] = None


class AnalysisResultOut(BaseModel):
    call_site_id: str
    window_start: datetime
    window_end: datetime
    control_n: int
    control_successes: int
    weak_n: int
    weak_successes: int
    p_value: Optional[float]
    significant: bool
    estimated_samples_needed: Optional[int]
    computed_at: datetime

    class Config:
        from_attributes = True
