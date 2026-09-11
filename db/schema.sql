-- Continuous Model-Tier Evaluation System: schema

CREATE TABLE IF NOT EXISTS call_site_configs (
    call_site_id            TEXT PRIMARY KEY,
    control_model           TEXT NOT NULL,
    weak_model              TEXT NOT NULL,
    sample_rate             DOUBLE PRECISION NOT NULL CHECK (sample_rate >= 0 AND sample_rate <= 1),
    salt                    TEXT NOT NULL,
    outcome_score_type      TEXT NOT NULL CHECK (outcome_score_type IN ('boolean', 'scale')),
    scale_min               DOUBLE PRECISION,
    scale_max               DOUBLE PRECISION,
    scale_success_threshold DOUBLE PRECISION,
    enabled                 BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (control_model <> weak_model),
    CHECK (
        outcome_score_type = 'boolean'
        OR (scale_min IS NOT NULL AND scale_max IS NOT NULL AND scale_max > scale_min)
    )
);

CREATE TABLE IF NOT EXISTS config_audit_log (
    id           BIGSERIAL PRIMARY KEY,
    call_site_id TEXT NOT NULL,
    changed_by   TEXT,
    change       JSON NOT NULL,
    changed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_config_audit_log_call_site ON config_audit_log (call_site_id, changed_at DESC);

-- First-write-wins tier assignment per (call_site_id, scope_id). This is the
-- canonical source of truth for a scope's tier: the client-side hash is only
-- used to compute the *candidate* assignment on first sight of a scope_id,
-- so that rotating `salt` cannot flip an in-flight scope mid-lifetime.
CREATE TABLE IF NOT EXISTS bucket_assignments (
    call_site_id TEXT NOT NULL,
    scope_id     TEXT NOT NULL,
    tier         TEXT NOT NULL CHECK (tier IN ('control', 'weak')),
    salt_used    TEXT NOT NULL,
    assigned_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (call_site_id, scope_id)
);

CREATE TABLE IF NOT EXISTS call_events (
    id           BIGSERIAL PRIMARY KEY,
    call_site_id TEXT NOT NULL,
    scope_id     TEXT NOT NULL,
    model_used   TEXT NOT NULL,
    tier         TEXT NOT NULL CHECK (tier IN ('control', 'weak')),
    request_id   TEXT,
    occurred_at  TIMESTAMPTZ NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_call_events_site_scope ON call_events (call_site_id, scope_id);
CREATE INDEX IF NOT EXISTS idx_call_events_site_time ON call_events (call_site_id, occurred_at);

CREATE TABLE IF NOT EXISTS outcome_events (
    id           BIGSERIAL PRIMARY KEY,
    call_site_id TEXT NOT NULL,
    scope_id     TEXT NOT NULL,
    score        DOUBLE PRECISION NOT NULL,
    score_type   TEXT NOT NULL CHECK (score_type IN ('boolean', 'scale')),
    source       TEXT,
    occurred_at  TIMESTAMPTZ NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_outcome_events_site_scope ON outcome_events (call_site_id, scope_id);
CREATE INDEX IF NOT EXISTS idx_outcome_events_site_time ON outcome_events (call_site_id, occurred_at);

CREATE TABLE IF NOT EXISTS analysis_results (
    id                       BIGSERIAL PRIMARY KEY,
    call_site_id             TEXT NOT NULL,
    window_start             TIMESTAMPTZ NOT NULL,
    window_end               TIMESTAMPTZ NOT NULL,
    control_n                INTEGER NOT NULL,
    control_successes        INTEGER NOT NULL,
    weak_n                   INTEGER NOT NULL,
    weak_successes           INTEGER NOT NULL,
    p_value                  DOUBLE PRECISION,
    significant              BOOLEAN NOT NULL DEFAULT FALSE,
    estimated_samples_needed INTEGER,
    computed_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_analysis_results_site_time ON analysis_results (call_site_id, computed_at DESC);
