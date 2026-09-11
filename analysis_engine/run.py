"""Batch analysis job: for each enabled call site, join call_events with
outcome_events over a rolling window (warehouse batch join, per design),
compute the tier comparison, and write a new analysis_results row.

Run once (`python -m analysis_engine.run`) on a schedule (cron/systemd timer/
orchestrator of choice) or with `--loop` for a simple built-in scheduler.
"""
import argparse
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from common.db import session_scope, init_db
from common.models import CallSiteConfig, BucketAssignment, OutcomeEvent, AnalysisResult
from analysis_engine.stats import compare_tiers

logger = logging.getLogger("analysis_engine")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

DEFAULT_WINDOW_DAYS = 30


def normalize_success(score: float, score_type: str, config: CallSiteConfig) -> bool:
    if score_type == "boolean":
        return score >= 0.5
    threshold = config.scale_success_threshold
    if threshold is None:
        threshold = (config.scale_min + config.scale_max) / 2
    return score >= threshold


def analyze_call_site(db, config: CallSiteConfig, window_days: int) -> AnalysisResult:
    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(days=window_days)

    # Canonical scope -> tier mapping (source of truth, not re-derived from events)
    assignments = db.scalars(
        select(BucketAssignment).where(BucketAssignment.call_site_id == config.call_site_id)
    ).all()
    scope_tier = {a.scope_id: a.tier for a in assignments}

    outcomes = db.scalars(
        select(OutcomeEvent)
        .where(OutcomeEvent.call_site_id == config.call_site_id)
        .where(OutcomeEvent.occurred_at >= window_start)
        .where(OutcomeEvent.occurred_at <= window_end)
        .order_by(OutcomeEvent.occurred_at.asc())
    ).all()

    # A scope may report more than one outcome event (e.g. an updated rating);
    # take the most recent one per scope as that scope's outcome for this run.
    latest_outcome_by_scope = {}
    for event in outcomes:
        latest_outcome_by_scope[event.scope_id] = event

    tier_totals = defaultdict(lambda: {"n": 0, "successes": 0})
    for scope_id, event in latest_outcome_by_scope.items():
        tier = scope_tier.get(scope_id)
        if tier is None:
            logger.warning(
                "outcome event for unknown scope_id=%s at call_site=%s (no bucket assignment on record)",
                scope_id, config.call_site_id,
            )
            continue
        tier_totals[tier]["n"] += 1
        if normalize_success(event.score, event.score_type, config):
            tier_totals[tier]["successes"] += 1

    comparison = compare_tiers(
        control_n=tier_totals["control"]["n"],
        control_successes=tier_totals["control"]["successes"],
        weak_n=tier_totals["weak"]["n"],
        weak_successes=tier_totals["weak"]["successes"],
    )

    result = AnalysisResult(
        call_site_id=config.call_site_id,
        window_start=window_start,
        window_end=window_end,
        control_n=comparison.control_n,
        control_successes=comparison.control_successes,
        weak_n=comparison.weak_n,
        weak_successes=comparison.weak_successes,
        p_value=comparison.p_value,
        significant=comparison.significant,
        estimated_samples_needed=comparison.estimated_samples_needed,
    )
    db.add(result)
    logger.info(
        "call_site=%s control=%s/%s weak=%s/%s p=%s significant=%s",
        config.call_site_id, comparison.control_successes, comparison.control_n,
        comparison.weak_successes, comparison.weak_n, comparison.p_value, comparison.significant,
    )
    return result


def run_once(window_days: int = DEFAULT_WINDOW_DAYS) -> int:
    with session_scope() as db:
        configs = db.scalars(select(CallSiteConfig).where(CallSiteConfig.enabled.is_(True))).all()
        for config in configs:
            analyze_call_site(db, config, window_days)
        return len(configs)


def main():
    parser = argparse.ArgumentParser(description="Model-tier evaluation analysis job")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--loop", action="store_true", help="run continuously instead of once")
    parser.add_argument("--interval-seconds", type=int, default=300)
    args = parser.parse_args()

    init_db()

    if not args.loop:
        n = run_once(args.window_days)
        logger.info("analyzed %d call site(s)", n)
        return

    logger.info("starting analysis loop, interval=%ds", args.interval_seconds)
    while True:
        try:
            run_once(args.window_days)
        except Exception:
            logger.exception("analysis run failed, will retry next interval")
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
