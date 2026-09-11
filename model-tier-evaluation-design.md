# Design Doc: Continuous Model-Tier Evaluation System

## 1. Summary

A system for safely testing whether cheaper/weaker LLMs can replace more expensive models in production, using real user traffic and real outcome signals instead of offline benchmarks.

A small percentage of traffic (developer-configured, e.g. 5%) is routed to a "weak" model instead of the default "control" model, on a per-call-site, per-scope basis. Every call is tagged with its assigned model and tier in telemetry. When the application reports a success/failure outcome for that scope, the system can continuously compute whether the weak model is performing statistically as well as the control model — giving product owners a live, data-backed answer to "is the cheap model good enough here?"

Think of it as feature-flagging infrastructure, but the "flag" is which model tier handles a given interaction, and the "metric" is real user-reported success.

## 2. Core Concepts

**Call site** — A named location in the application where an LLM is invoked (e.g. `chat-reply`, `summarize`, `title-generation`). Each call site is configured and evaluated independently, since different call sites may use different weak/control model pairs and may have completely different success characteristics.

**Scope ID** — A developer-supplied identifier representing the unit of analysis for an outcome (e.g. a session ID, a conversation ID, a task ID). The developer chooses the granularity that best matches where they can actually capture a success signal. The system is agnostic to what a scope ID represents.

**Tier** — Either `control` (the normal/strong model) or `weak` (the candidate cheaper model) for a given call site + scope ID combination.

**Bucket key** — The combination of `call_site + scope_id` that determines tier assignment. The same scope ID may be `control` for one call site and `weak` for another — each call site's experiment is fully independent.

## 3. Design Principles (from requirements)

1. **No mid-scope contamination.** Once a bucket key (call site + scope ID) is assigned a tier, every call under that key uses that same tier for its entire lifetime. Mixing tiers within one scope would wash out the signal, since a strong model call could mask a weak model's earlier failure (or vice versa).
2. **Granularity is pluggable.** The system doesn't assume session-level or call-level scoping — the developer decides what scope ID means for their product, based on where they can realistically capture outcome signal.
3. **Deterministic, stateless-capable bucketing.** Tier assignment is computed via a hash of `call_site + scope_id + salt`, so it's reproducible without a mandatory round trip to the backend, while still being centrally auditable (the backend knows the same salt and rate).
4. **Explicit outcome signals first.** Start with developer-triggered success/failure signals (e.g. thumbs up/down). Implicit signals (abandonment, retries, etc.) are a future extension.
5. **Continuous, not batch.** Analysis is a live rolling computation, not an on-demand report, since usage patterns and model behavior drift over time.

## 4. System Components

### 4.1 Config Service

Owns per-call-site experiment configuration:

- `call_site_id`
- `control_model`
- `weak_model`
- `sample_rate` (e.g. 0.05)
- `salt` (used for deterministic bucketing; rotatable to force re-randomization)
- `outcome_score_type` (`boolean` | `scale`, and scale bounds if applicable)
- enabled/disabled toggle per call site

Product owners manage this through a dashboard or API, similar to managing a feature flag.

### 4.2 Client SDK

Wraps LLM calls. Responsibilities:

1. On a call for a given `call_site_id` + `scope_id`, check whether a tier is already assigned (local cache or backend lookup).
2. If not yet assigned: compute `hash(call_site_id + scope_id + salt) mod 1.0 < sample_rate` → assign `weak` or `control`. Cache this decision keyed by bucket key.
3. Route the call to the appropriate model based on the assigned tier.
4. Emit a call-level telemetry event (see 4.3) including which model was actually used and the tier.

Because the hash is deterministic and the salt/rate are fetched once (or infrequently) from the config service, the SDK can operate mostly offline after initial sync, without needing a network round trip per call.

### 4.3 Telemetry Schema

**Call event** (emitted per LLM call):

| Field | Description |
|---|---|
| `call_site_id` | Which call site this call belongs to |
| `scope_id` | Developer-supplied scope identifier |
| `model_used` | Actual model invoked |
| `tier` | `control` or `weak` |
| `timestamp` | |
| `trace/input/output` | Whatever the underlying telemetry provider already captures |

**Outcome event** (emitted asynchronously, when a success signal becomes available):

| Field | Description |
|---|---|
| `call_site_id` | |
| `scope_id` | |
| `score` | Raw value — boolean or numeric scale |
| `score_type` | `boolean` or `scale` (matches config) |
| `timestamp` | |

Outcome events are joined to call events later by `call_site_id + scope_id`, not attached synchronously, since real outcome signals (e.g. a thumbs-up click) typically arrive after the call itself completes.

Scale scores are stored raw for future richer analysis, but normalized to boolean (e.g. threshold at midpoint) for the core comparison engine to start.

### 4.4 Analysis Engine

Runs continuously per call site:

1. Maintain rolling counts of successes/failures per tier (`control` vs `weak`) within a configurable time window.
2. Recompute a significance test (e.g. two-proportion z-test / chi-squared test for boolean scores) on a cheap schedule (e.g. every few minutes) rather than on every single event.
3. Expose current state: success rate per tier, whether the difference is statistically significant, and an estimate of how many more samples are needed to reach significance if not yet conclusive.

Output surfaces as a live dashboard per call site — not a one-shot report — so product owners can watch confidence build over time and see if it drifts as usage or models change.

## 5. Open Items / Future Extensions

- **Implicit outcome signals** (abandonment, retries, edits) — deferred; explicit signals ship first to keep scoring semantics unambiguous.
- **Scale-score native analysis** (t-test / Mann-Whitney U on raw ratings) — boolean collapsing ships first; raw scores are retained so this can be added without a schema change.
- **Guaranteed-exact sample rates** — current design uses hash-based approximate sampling; an explicit assignment table is a possible alternative if exact percentages become important.
- **Backend-only bucketing mode** — for cases needing tighter central control than client-side deterministic hashing allows.
