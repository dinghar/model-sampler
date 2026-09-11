import math

from analysis_engine.stats import (
    two_proportion_z_test, compare_tiers, MIN_SAMPLES_FOR_SIGNIFICANCE, ALPHA
)


def test_z_test_matches_known_reference_value():
    # Hand-derived reference for this exact input (pooled two-proportion z-test):
    # p1=.45, p2=.30, p_pool=.375, se=sqrt(.375*.625*(1/100+1/100))=.06846,
    # z=(.45-.30)/.06846=2.191, two-sided p = 2*(1-Phi(2.191)) ~= 0.0285
    p = two_proportion_z_test(control_successes=45, control_n=100, weak_successes=30, weak_n=100)
    assert p is not None
    assert math.isclose(p, 0.0285, abs_tol=0.001)


def test_identical_rates_give_high_p_value():
    p = two_proportion_z_test(control_successes=50, control_n=100, weak_successes=50, weak_n=100)
    assert p == 1.0


def test_empty_group_returns_none():
    assert two_proportion_z_test(0, 0, 10, 20) is None
    assert two_proportion_z_test(10, 20, 0, 0) is None


def test_significance_gated_by_minimum_sample_size():
    # huge relative gap but tiny n -- should NOT be flagged significant
    # despite a low p-value, because of the MIN_SAMPLES_FOR_SIGNIFICANCE guardrail
    result = compare_tiers(control_n=5, control_successes=5, weak_n=5, weak_successes=0)
    assert result.p_value is not None and result.p_value < ALPHA
    assert result.significant is False


def test_significance_reached_with_enough_samples_and_real_gap():
    n = MIN_SAMPLES_FOR_SIGNIFICANCE * 4
    result = compare_tiers(control_n=n, control_successes=int(n * 0.9),
                            weak_n=n, weak_successes=int(n * 0.5))
    assert result.significant is True
    assert result.p_value < ALPHA


def test_no_effect_yields_no_sample_estimate():
    result = compare_tiers(control_n=100, control_successes=50, weak_n=100, weak_successes=50)
    assert result.estimated_samples_needed is None


def test_small_effect_yields_larger_sample_estimate_than_large_effect():
    # n below MIN_SAMPLES_FOR_SIGNIFICANCE on both so neither is ever flagged
    # `significant` (which would otherwise suppress the sample-size estimate)
    small_gap = compare_tiers(control_n=20, control_successes=11, weak_n=20, weak_successes=9)
    large_gap = compare_tiers(control_n=20, control_successes=18, weak_n=20, weak_successes=2)
    assert small_gap.significant is False and large_gap.significant is False
    assert small_gap.estimated_samples_needed > large_gap.estimated_samples_needed
