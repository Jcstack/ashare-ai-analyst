# Roadmap

> **Status:** post-`v2.0.0`. This roadmap is grounded in a multi-agent code audit of the
> v2 codebase (2026-06), cross-checked against the open-source LLM-quant landscape.
> Every item below cites concrete `file:line` evidence so it can be picked up directly.
>
> **Reminder:** this is a **simulation-only** personal learning project — no live order
> routing, outputs are **not investment advice** (see the disclaimer in `README.md`).

## Guiding priority

The decision machinery is genuine quant (sequential Bayesian belief → fractional-Kelly →
VaR, not LLM-prompt-glue). The single highest-leverage gap is **validation**: the
*inputs* to that machinery — likelihood tables, regime priors, sentiment→position
thresholds — are expert-assigned constants with **no published backtest** proving they
predict anything. So the ordering principle here is: **move the project from "asserted"
to "shown"**, fix the real defects found along the way, and pay down the duplication that
inflates LOC without adding depth.

Tiers map to: **P0 修 bug · P1 去重 / 清理 · P2 补验证 / 设计 · P3 采用**.
Effort: **S** ≈ <½ day · **M** ≈ 1–2 days · **L** ≈ multi-day.

---

## P0 — Correctness bugs (real defects; fix first)

### P0.1 — `preflight` circuit-breaker gate is a no-op  · **S**
- **Evidence:** `src/trading/preflight.py:135-151`. `_check_circuit_breaker()` does
  `breaker = CircuitBreaker()` then inspects `breaker._state`, which a freshly
  constructed breaker always initializes to `NORMAL`. It never calls
  `load_from_redis()` / `is_halted()`, so the **persisted halt state is never read** and
  this pre-order gate effectively *always passes*.
- **Why it matters:** the circuit breaker's Redis persistence works elsewhere
  (`src/risk/circuit_breaker.py` load/save), but the preflight layer silently bypasses
  it — a halted system would still pass preflight.
- **Fix:** construct/inject the shared breaker and call `load_from_redis()` then
  `is_halted()` (or inject the live instance the loop already holds rather than `new`).
- **Acceptance:** a unit test that sets a halted state in Redis (or a mocked breaker)
  asserts `_check_circuit_breaker()` returns `passed=False`.

### P0.2 — `preflight` advertises a T+1 sellability check it never runs  · **S**
- **Evidence:** docstring at `src/trading/preflight.py:38-39` lists "T+1 sellability",
  but `check()` (`:75-87`) never calls `can_sell_today` — no T+1 enforcement runs in
  preflight.
- **Fix:** either add a real `_check_t1_sellability()` for `sell`/`reduce` actions and
  append it in `check()`, or remove the claim from the docstring. Prefer adding the check.
- **Acceptance:** test that a same-day-bought position fails preflight on `sell`.

### P0.3 — `review_agent` score-cutoff inconsistency  · **S**
- **Evidence:** test docstring says "skip < 0.65" but fallback code uses `< 0.55`
  (`src/recommendation/review_agent.py:609`); the LLM path uses `0.65` (`:538`). The test
  only asserts `0.5` is dropped, so it passes by luck and masks the mismatch.
- **Fix:** pick one threshold (or name both intentionally as constants) and make the test
  assert the boundary.
- **Acceptance:** a boundary test at the chosen cutoff (e.g. `0.64` drops, `0.65` keeps).

---

## P1 — Dedup, dead code & honest naming (pay down the LOC that isn't depth)

### P1.1 — A-share constraints reimplemented 4× (drift risk)  · **M**
- **Evidence:** lot-size / price-limit / T+1 / stamp-tax logic lives independently in
  `src/trading/constraints.py`, `src/agent_loop/ashare_constraints.py`,
  `src/strategy/base.py`, and `src/backtest/engine.py` (plus lot-rounding in
  `src/risk/position_sizer.py`). No single source of truth.
- **Fix:** extract one canonical `ashare_rules` module (board detection, price limits,
  T+1, lots, stamp-duty asymmetry); have the others import it.
- **Acceptance:** one module owns the constants; the other call sites delegate; tests for
  the rules live in one place.

### P1.2 — Two parallel causal-chain engines in production  · **M**
- **Evidence:** `ImpactChainEngine` (`src/intelligence/impact_chain.py`, used by
  rotation/relevance/causal-chain-agent) vs `CausalChainConstructor` + `EventImpactEngine`
  (`causal_chain.py` / `impact_engine.py`, used by aggregator/web/investment_director) —
  separate template formats, separate SQLite tables, overlapping purpose.
- **Fix:** choose one, migrate callers, delete the other (or clearly demote one to a
  thin adapter).
- **Acceptance:** a single chain API; no duplicate SQLite schemas for the same concept.

### P1.3 — Two overlapping data-failover mechanisms  · **M**
- **Evidence:** the hot path `fetcher.py:242-397` hardcodes an inline 4-source try/except
  cascade and does **not** consult `DataSourceRouter` (`src/data/source_router.py`), whose
  health/DEGRADED/DOWN tracking is used only by `realtime.py`/`news_fetcher.py`.
- **Fix:** route the core cascade through `DataSourceRouter` (single failover brain) or
  delete the router if the inline cascade is preferred.
- **Acceptance:** one failover mechanism governs `fetch_daily_ohlcv`.

### P1.4 — Dead code  · **S**
- `src/quant/alternative_bars.py` (391 LOC) — **0 production callers** (verified).
- `RecStore.get_sector_win_rates` (`src/recommendation/rec_store.py:696`) — **0 callers**,
  and buggy (`GROUP BY style` but docstring/return claim per-sector).
- `OvernightRiskProfile.to_context_str` (`src/recommendation/overnight_risk.py:40-57`) —
  built but never called outside its own test.
- Deprecated prompt constants `analysis_frameworks.py:18-66`
  (`PROFESSIONAL_/QUICK_ANALYSIS_FRAMEWORK`, explicitly marked DEPRECATED).
- **Fix:** delete, or move to a clearly-labeled `experimental/` namespace with a reason.
- **Acceptance:** grep shows no orphan modules advertised as features; CI/tests green.

### P1.5 — Overstated / mislabeled naming  · **S**
- **"Alpha158":** `scripts/qlib_worker.py:198-244` hand-rolls only ~20 Qlib-DSL factors and
  never instantiates qlib's `Alpha158` handler; the whole qlib path degrades to `None` in
  CI/Docker. Rename to "~20 custom alpha factors" and document the optional qlib bridge.
- **"Causal impact chains":** `impact_chain.py` is a hand-authored `CHAIN_TEMPLATES` table
  selected by keyword substring-counting with `confidence` hardcoded `0.7` — it is curated
  domain knowledge + keyword matching, **not inferred causality**. Rename / document
  honestly ("rule-based impact templates").
- **"Information Coefficient":** `qlib_worker.py:281` uses a single-series `autocorr()` as
  IC — not a cross-sectional IC vs forward returns. Fix the computation or rename.
- **Acceptance:** names match what the code does; docstrings stop overclaiming.

### P1.6 — Stubs hidden behind advertised features  · **S**
- `ConfidenceCalibrator._sector_calibration` always returns `0.0`
  (`src/agent_loop/confidence_calibrator.py:266-270`) yet is wired in at `:72` — one of
  three advertised calibration dimensions silently contributes nothing.
- `LiveBroker` is `NotImplementedError` (`src/web/services/broker_interface.py:243-273`) —
  fine for simulation-only, but the API surface should make the "trading" path's
  non-functional-by-design status explicit.
- **Fix:** implement the sector dimension or remove it from the advertised set; label the
  live path clearly.
- **Acceptance:** no advertised dimension is a constant `0.0`; docs state live-broker is a
  stub.

---

## P2 — Validation & design (the tier that actually moves the project's standing)

### P2.1 — Publish an out-of-sample A-share backtest  · **L**  ⭐ highest leverage
- **Why:** the entire investing thesis is currently *asserted*, not *shown*. One credible
  results table changes the project's standing more than any code change.
- **What:** the backtest engine already exists and is A-share-correct
  (`src/backtest/engine.py`: T+1, board price-limit halts, 100-share lots, sell-side stamp
  tax, round-trip PnL). Run the **v2 signal/sizing stack** (not just the legacy strategies)
  through a real out-of-sample window and publish equity curve, Sharpe, max drawdown,
  turnover, and hit-rate vs a buy-and-hold / index baseline.
- **Acceptance:** a reproducible `scripts/backtest_v2.py` + a results section in the README
  (or `docs/`), with the window, universe, costs, and baseline stated honestly.
- **Note:** bridging the v2 agent-loop signals into the legacy backtest engine is the main
  work — the two are currently architecturally forked (the OODA loop never touches
  `src/backtest/`). This is the scaffold to build first.

### P2.2 — Fix the Bayesian likelihood derivation  · **M**
- **Evidence:** `src/agent_loop/outcome_tracker.py:576-583` sets
  `p_given_bull = correct/total` (a *hit-rate* ≈ `P(state | signal)`) into the slot the
  engine consumes as the *likelihood* `P(signal | state)`, then sets
  `p_given_bear = 1.0 - p_given_bull`. That complementarity holds for **posteriors across
  hypotheses**, not for **likelihoods** — the tell that accuracy is being mislabeled as a
  likelihood.
- **Why:** this is the conceptual heart of the project's differentiator; getting it
  actually-correct matters more than any new feature.
- **Fix:** estimate `P(signal-strength | true-state)` from binned conditional frequencies
  of outcomes (condition on realized state, not on correctness); drop the `1 - p`
  construction.
- **Acceptance:** a documented derivation + a unit test on a synthetic outcome set where
  the recovered likelihoods match the generating process.

### P2.3 — Close test gaps in the feedback loop  · **M**
- **Evidence:** no dedicated unit test for `OutcomeTracker` (the feedback heart — only
  covered indirectly via integration). T+1/3/5 horizons use `timedelta(days=1/3/5)`
  (`outcome_tracker.py:315-341`) — **calendar** days, so T+1 can land on a weekend/holiday.
- **Fix:** add a focused `test_outcome_tracker.py`; switch horizon arithmetic to **trading
  days** via `TradingCalendar`.
- **Acceptance:** OutcomeTracker has direct tests; a T+N that crosses a weekend resolves to
  the next trading day.

### P2.4 — Validate (or de-risk) the LLM-debate dependency  · **L**
- **Evidence:** for buys the pipeline hard-refuses without the debate engine
  (`src/agent_loop/decision_pipeline.py:434-440`), so live decision quality rests on an LLM
  whose output is not independently validated in-repo.
- **Fix:** add an evaluation harness measuring debate-output quality against labeled
  outcomes, **or** allow the non-LLM path to issue conservative buys so a bad/absent oracle
  degrades gracefully.
- **Acceptance:** a debate-quality metric tracked over time, or a documented non-LLM
  fallback for buys.

---

## P3 — Adoption (only worthwhile *after* P2 shows results)

### P3.1 — One-command quickstart  · **M**
- A `docker compose up` (or `make demo`) that boots the stack against a sample dataset so
  onboarding isn't heavier than peers'. Today the setup (Celery + Redis + AKShare +
  multi-subsystem) is the friction that caps adoption.

### P3.2 — Technical write-up + demo  · **M**
- A short post documenting the OODA loop + Bayesian-calibration design **with the P2.1
  backtest results** and a demo GIF. Stars follow a reproducible demo and an honest results
  table — not LOC. Realistic ceiling without this: low hundreds of stars; with it:
  low thousands, on the defensible hook *"the most rigorously-engineered A-share agent
  framework with actual decision theory inside."*

---

## Honest framing

This is the best-engineered and most A-share-native member of the solo/hobbyist
LLM-agent trading cluster (peers: TradingAgents, ai-hedge-fund, TradingAgents-CN) — a real
quant decision core behind cluster-leading test/CI discipline. It is **not** a peer of
research-grade platforms (qlib, AI4Finance) and its investing thesis is, as of `v2.0.0`,
**entirely unvalidated**. P2.1 is the item that changes that.
