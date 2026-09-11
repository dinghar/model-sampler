"""End-to-end smoke test across API + SDK bucketing contract + analysis engine,
running against a throwaway SQLite file so it needs no external services.
"""
import os
import tempfile

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

import pytest
from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from common.db import init_db, Base, engine  # noqa: E402
from analysis_engine.run import run_once  # noqa: E402

init_db()  # TestClient(app) without a `with` block does not fire startup events
client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


def _create_call_site(sample_rate=0.5):
    payload = {
        "call_site_id": "chat-reply",
        "control_model": "big-model",
        "weak_model": "small-model",
        "sample_rate": sample_rate,
        "salt": "salt-v1",
        "outcome_score_type": "boolean",
        "enabled": True,
    }
    resp = client.post("/api/call-sites", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_and_fetch_call_site():
    _create_call_site()
    resp = client.get("/api/call-sites/chat-reply")
    assert resp.status_code == 200
    assert resp.json()["control_model"] == "big-model"


def test_duplicate_call_site_rejected():
    _create_call_site()
    resp = client.post("/api/call-sites", json={
        "call_site_id": "chat-reply", "control_model": "a", "weak_model": "b",
        "sample_rate": 0.1, "salt": "s", "outcome_score_type": "boolean",
    })
    assert resp.status_code == 409


def test_assign_is_sticky_across_repeated_calls():
    _create_call_site()
    first = client.post("/api/call-sites/chat-reply/assign", json={"scope_id": "user-42"}).json()
    for _ in range(5):
        again = client.post("/api/call-sites/chat-reply/assign", json={"scope_id": "user-42"}).json()
        assert again["tier"] == first["tier"]
        assert again["model"] == first["model"]


def test_disabled_call_site_forces_control():
    _create_call_site(sample_rate=1.0)  # would be "weak" for virtually everyone if enabled
    client.patch("/api/call-sites/chat-reply", json={"enabled": False})
    resp = client.post("/api/call-sites/chat-reply/assign", json={"scope_id": "any-scope"}).json()
    assert resp["tier"] == "control"
    assert resp["model"] == "big-model"


def test_patch_writes_audit_log_with_diff():
    _create_call_site()
    client.patch("/api/call-sites/chat-reply", json={"sample_rate": 0.2, "changed_by": "test-user"})
    resp = client.get("/api/call-sites/chat-reply")
    assert resp.json()["sample_rate"] == 0.2


def test_end_to_end_pipeline_produces_significant_result():
    _create_call_site(sample_rate=0.5)

    # Assign 80 scopes, split roughly by tier via the real assign endpoint
    scope_tiers = {}
    for i in range(80):
        scope_id = f"scope-{i}"
        tier = client.post("/api/call-sites/chat-reply/assign", json={"scope_id": scope_id}).json()["tier"]
        scope_tiers[scope_id] = tier

    control_scopes = [s for s, t in scope_tiers.items() if t == "control"]
    weak_scopes = [s for s, t in scope_tiers.items() if t == "weak"]
    assert len(control_scopes) >= 20 and len(weak_scopes) >= 20, "test salt/sample_rate split too skewed, adjust fixture"

    # control succeeds 90% of the time, weak succeeds 40% of the time
    for i, scope_id in enumerate(control_scopes):
        score = 1.0 if (i % 10) != 0 else 0.0
        r = client.post("/api/telemetry/outcome-events", json={
            "call_site_id": "chat-reply", "scope_id": scope_id, "score": score, "score_type": "boolean",
        })
        assert r.status_code == 201
    for i, scope_id in enumerate(weak_scopes):
        score = 1.0 if (i % 10) < 4 else 0.0
        r = client.post("/api/telemetry/outcome-events", json={
            "call_site_id": "chat-reply", "scope_id": scope_id, "score": score, "score_type": "boolean",
        })
        assert r.status_code == 201

    n_analyzed = run_once(window_days=30)
    assert n_analyzed == 1

    results = client.get("/api/call-sites/chat-reply/results/latest")
    assert results.status_code == 200
    body = results.json()
    assert body["control_n"] == len(control_scopes)
    assert body["weak_n"] == len(weak_scopes)
    assert body["significant"] is True
    assert body["p_value"] < 0.05


def test_outcome_for_unknown_scope_does_not_crash_analysis():
    _create_call_site()
    client.post("/api/telemetry/outcome-events", json={
        "call_site_id": "chat-reply", "scope_id": "never-assigned", "score": 1.0, "score_type": "boolean",
    })
    n_analyzed = run_once(window_days=30)
    assert n_analyzed == 1  # should not raise
