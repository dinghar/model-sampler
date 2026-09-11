from sqlalchemy import (
    Column, String, Float, Boolean, DateTime, BigInteger, Integer, JSON, CheckConstraint, Index, func
)

from common.db import Base

# SQLite only auto-generates rowid-alias primary keys for an `Integer` column,
# not `BigInteger` -- this variant keeps BIGSERIAL semantics on Postgres while
# still working against SQLite in tests.
BigIntegerPK = BigInteger().with_variant(Integer, "sqlite")


class CallSiteConfig(Base):
    __tablename__ = "call_site_configs"

    call_site_id = Column(String, primary_key=True)
    control_model = Column(String, nullable=False)
    weak_model = Column(String, nullable=False)
    sample_rate = Column(Float, nullable=False)
    salt = Column(String, nullable=False)
    outcome_score_type = Column(String, nullable=False)
    scale_min = Column(Float, nullable=True)
    scale_max = Column(Float, nullable=True)
    scale_success_threshold = Column(Float, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("sample_rate >= 0 AND sample_rate <= 1", name="ck_sample_rate_range"),
        CheckConstraint("outcome_score_type IN ('boolean', 'scale')", name="ck_outcome_score_type"),
    )


class ConfigAuditLog(Base):
    __tablename__ = "config_audit_log"

    id = Column(BigIntegerPK, primary_key=True, autoincrement=True)
    call_site_id = Column(String, nullable=False, index=True)
    changed_by = Column(String, nullable=True)
    change = Column(JSON, nullable=False)
    changed_at = Column(DateTime(timezone=True), server_default=func.now())


class BucketAssignment(Base):
    __tablename__ = "bucket_assignments"

    call_site_id = Column(String, primary_key=True)
    scope_id = Column(String, primary_key=True)
    tier = Column(String, nullable=False)
    salt_used = Column(String, nullable=False)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("tier IN ('control', 'weak')", name="ck_bucket_tier"),
    )


class CallEvent(Base):
    __tablename__ = "call_events"

    id = Column(BigIntegerPK, primary_key=True, autoincrement=True)
    call_site_id = Column(String, nullable=False)
    scope_id = Column(String, nullable=False)
    model_used = Column(String, nullable=False)
    tier = Column(String, nullable=False)
    request_id = Column(String, nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    received_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_call_events_site_scope", "call_site_id", "scope_id"),
        Index("idx_call_events_site_time", "call_site_id", "occurred_at"),
        CheckConstraint("tier IN ('control', 'weak')", name="ck_call_event_tier"),
    )


class OutcomeEvent(Base):
    __tablename__ = "outcome_events"

    id = Column(BigIntegerPK, primary_key=True, autoincrement=True)
    call_site_id = Column(String, nullable=False)
    scope_id = Column(String, nullable=False)
    score = Column(Float, nullable=False)
    score_type = Column(String, nullable=False)
    source = Column(String, nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    received_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_outcome_events_site_scope", "call_site_id", "scope_id"),
        Index("idx_outcome_events_site_time", "call_site_id", "occurred_at"),
        CheckConstraint("score_type IN ('boolean', 'scale')", name="ck_outcome_score_type"),
    )


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(BigIntegerPK, primary_key=True, autoincrement=True)
    call_site_id = Column(String, nullable=False)
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    control_n = Column(BigInteger, nullable=False)
    control_successes = Column(BigInteger, nullable=False)
    weak_n = Column(BigInteger, nullable=False)
    weak_successes = Column(BigInteger, nullable=False)
    p_value = Column(Float, nullable=True)
    significant = Column(Boolean, nullable=False, default=False)
    estimated_samples_needed = Column(BigInteger, nullable=True)
    computed_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_analysis_results_site_time", "call_site_id", "computed_at"),
    )
