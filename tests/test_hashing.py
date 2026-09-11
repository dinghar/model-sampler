import math

from scipy import stats as scipy_stats

from sdk.hashing import assign_tier, bucket_fraction


def test_deterministic_same_inputs_same_output():
    results = {
        assign_tier("chat-reply", "scope-123", "salt-v1", 0.05) for _ in range(50)
    }
    assert len(results) == 1


def test_different_call_sites_are_independent():
    # Same scope_id, same salt, different call sites should not be perfectly
    # correlated -- guards against accidentally hashing in a way that makes
    # call_site_id not actually participate in the bucket decision.
    site_a = [assign_tier("site-a", f"scope-{i}", "salt", 0.5) for i in range(2000)]
    site_b = [assign_tier("site-b", f"scope-{i}", "salt", 0.5) for i in range(2000)]
    agreement = sum(1 for a, b in zip(site_a, site_b) if a == b) / len(site_a)
    # under independence, ~50% agreement expected; allow generous slack
    assert 0.40 < agreement < 0.60


def test_salt_rotation_changes_assignment_distribution_not_correlated():
    scope_ids = [f"scope-{i}" for i in range(2000)]
    before = [assign_tier("site", s, "salt-v1", 0.5) for s in scope_ids]
    after = [assign_tier("site", s, "salt-v2", 0.5) for s in scope_ids]
    agreement = sum(1 for a, b in zip(before, after) if a == b) / len(before)
    assert 0.40 < agreement < 0.60


def test_distribution_matches_sample_rate_via_chi_squared():
    sample_rate = 0.05
    n = 20000
    weak_count = sum(
        1 for i in range(n) if assign_tier("chat-reply", f"scope-{i}", "salt", sample_rate) == "weak"
    )
    control_count = n - weak_count
    expected_weak = n * sample_rate
    expected_control = n * (1 - sample_rate)
    chi2, p_value = scipy_stats.chisquare(
        f_obs=[weak_count, control_count],
        f_exp=[expected_weak, expected_control],
    )
    # fail only if the deviation is implausible under the null (true rate = sample_rate)
    assert p_value > 0.001, (
        f"observed weak fraction {weak_count / n} deviates implausibly from {sample_rate}"
    )


def test_bucket_fraction_is_in_unit_interval():
    for i in range(500):
        f = bucket_fraction("site", f"scope-{i}", "salt")
        assert 0.0 <= f < 1.0


def test_invalid_sample_rate_rejected():
    import pytest
    with pytest.raises(ValueError):
        assign_tier("site", "scope", "salt", 1.5)
    with pytest.raises(ValueError):
        assign_tier("site", "scope", "salt", -0.1)
