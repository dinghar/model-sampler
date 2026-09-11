"""Statistics for comparing control vs. weak tier success rates.

Note on the "peeking problem" (see implementation-plan.md, Risk R2):
recomputing a plain two-proportion z-test on every scheduled run and treating
the first p < 0.05 as "done" inflates the false-positive rate above the
nominal level, because the test is being repeatedly re-applied to growing
data (optional stopping). This module mitigates that with a hard minimum
sample size per tier (MIN_SAMPLES_FOR_SIGNIFICANCE) before ever reporting
`significant=True`, but that is a partial guardrail, not a full fix. A
sequential/always-valid testing method is flagged as follow-up work rather
than built here, to avoid a speculative implementation before the guardrail
approach is signed off with a stats stakeholder (see implementation-plan.md
Section 7).
"""
from dataclasses import dataclass
from typing import Optional

from scipy import stats as scipy_stats

MIN_SAMPLES_FOR_SIGNIFICANCE = 30
ALPHA = 0.05
TARGET_POWER = 0.8


@dataclass
class ComparisonResult:
    control_n: int
    control_successes: int
    weak_n: int
    weak_successes: int
    p_value: Optional[float]
    significant: bool
    estimated_samples_needed: Optional[int]

    @property
    def control_rate(self) -> Optional[float]:
        return self.control_successes / self.control_n if self.control_n else None

    @property
    def weak_rate(self) -> Optional[float]:
        return self.weak_successes / self.weak_n if self.weak_n else None


def two_proportion_z_test(control_successes: int, control_n: int,
                           weak_successes: int, weak_n: int) -> Optional[float]:
    """Two-sided two-proportion z-test. Returns None if either group is empty."""
    if control_n == 0 or weak_n == 0:
        return None
    p1 = control_successes / control_n
    p2 = weak_successes / weak_n
    p_pool = (control_successes + weak_successes) / (control_n + weak_n)
    denom = p_pool * (1 - p_pool) * (1 / control_n + 1 / weak_n)
    if denom <= 0:
        # e.g. p_pool is 0 or 1 (every observation identical) -- no variance to test
        return None if p1 == p2 else 0.0
    z = (p1 - p2) / (denom ** 0.5)
    return float(2 * (1 - scipy_stats.norm.cdf(abs(z))))


def estimate_samples_needed_per_group(p1: float, p2: float, alpha: float = ALPHA,
                                       power: float = TARGET_POWER) -> Optional[int]:
    """Closed-form sample size per group for a two-proportion z-test
    (Fleiss/Cochran formula), to reach `power` at `alpha` for the *currently
    observed* effect size. This is a moving target -- as the observed effect
    size changes between runs, so does the estimate. Returns None if p1==p2
    (no detectable effect, i.e. infinite samples needed).
    """
    if p1 == p2:
        return None
    z_alpha = scipy_stats.norm.ppf(1 - alpha / 2)
    z_power = scipy_stats.norm.ppf(power)
    p_bar = (p1 + p2) / 2
    numerator = (
        z_alpha * (2 * p_bar * (1 - p_bar)) ** 0.5
        + z_power * (p1 * (1 - p1) + p2 * (1 - p2)) ** 0.5
    ) ** 2
    denominator = (p1 - p2) ** 2
    return max(1, int(numerator / denominator) + 1)


def compare_tiers(control_n: int, control_successes: int, weak_n: int, weak_successes: int) -> ComparisonResult:
    p_value = two_proportion_z_test(control_successes, control_n, weak_successes, weak_n)

    significant = (
        p_value is not None
        and p_value < ALPHA
        and control_n >= MIN_SAMPLES_FOR_SIGNIFICANCE
        and weak_n >= MIN_SAMPLES_FOR_SIGNIFICANCE
    )

    estimated_samples_needed = None
    if control_n > 0 and weak_n > 0 and not significant:
        p1 = control_successes / control_n
        p2 = weak_successes / weak_n
        needed_per_group = estimate_samples_needed_per_group(p1, p2)
        if needed_per_group is not None:
            # floor at the minimum-sample-size guardrail itself, so a case
            # like "power analysis says we already have enough, but we're
            # still below MIN_SAMPLES_FOR_SIGNIFICANCE" doesn't report
            # "0 more needed" right next to significant=False.
            floor = max(needed_per_group, MIN_SAMPLES_FOR_SIGNIFICANCE)
            estimated_samples_needed = max(0, floor - min(control_n, weak_n))

    return ComparisonResult(
        control_n=control_n,
        control_successes=control_successes,
        weak_n=weak_n,
        weak_successes=weak_successes,
        p_value=p_value,
        significant=significant,
        estimated_samples_needed=estimated_samples_needed,
    )
