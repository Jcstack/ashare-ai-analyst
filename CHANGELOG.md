# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [2.0.1] — Post-v2.0.0 hardening: honest backtest + audit-driven fixes

A multi-agent code audit of the v2 stack drove a round of correctness fixes,
honest validation, and de-duplication. Highlight: the **first out-of-sample
backtest** of the v2 signal/sizing stack — published with the candid result that
it shows **no demonstrated alpha** vs buy-and-hold (a drawdown-limiter that caps
trend upside). Still **simulation-only** — not investment advice.

### Added

- **Out-of-sample backtest of the v2 stack** (`docs/backtest-v2-results.md`,
  `scripts/backtest_v2.py`, `scripts/backtest_v2_universe.py`): bridges the v2
  signal/sizing stack into the A-share backtest engine (no look-ahead) and
  reports an honest equity curve, Sharpe, drawdown, and a buy-and-hold baseline
  over 2019–2024 (14 names). Result: +25.5% vs +351.7% buy-and-hold, 0/14. (#43, #59)
- **One-command offline demo** — `make demo` runs the v2 backtest on a bundled
  sample dataset with no Docker, API keys, or network. (#65)
- **`docs/how-it-works.md`** — newcomer overview tying the OODA loop and Bayesian
  calibration to the backtest finding; `ROADMAP.md` — tiered, evidence-grounded
  roadmap from the audit. (#41, #63)

### Fixed

- **Risk gates were no-ops** — `preflight` now actually reads the persisted
  circuit-breaker halt state (via `is_halted()`) and enforces T+1 sellability;
  `review_agent` buy/watch score cutoffs are named, documented constants. (#42)
- **Bayesian likelihood derivation** — `OutcomeTracker` now estimates genuine
  `P(evidence | state)` from conditional frequencies instead of mislabeling the
  hit-rate (and dropping the unjustified `p_bear = 1 − p_bull`). (#61)
- **T+N outcome horizons** use trading days (via `TradingCalendar`), not calendar
  days, so a T+1 lookup after a Friday no longer lands on a weekend; adds the
  first dedicated `OutcomeTracker` tests. (#61)

### Changed

- **Single source of truth for A-share constants** (`src/utils/ashare_constants.py`)
  — lot size, commission/stamp rates, and board price limits are imported instead
  of re-hardcoded across trading/strategy/backtest/risk. (#64)
- **Unified data-source health** on one shared `DataSourceRouter` — the daily
  fetcher, realtime, and news now record into and read from one health view
  (the `/admin` dashboard was previously empty). (#66)
- **Merged the two causal-chain engines** — `ImpactChainEngine` is now a thin
  adapter over the canonical `CausalChainConstructor`; stock resolution preserved
  via a shared sector→stock map; USD→gold transmission kept lossless. (#67)
- **LLM-debate dependency de-risked** — an opt-in (`allow_degraded_buys`, default
  off) lets the deterministic stack issue a damped buy when the debate engine is
  unavailable, instead of silently dropping the signal. (#61)
- **Honest naming** — "Qlib Alpha158" → custom alpha factors; "causal chains" →
  rule-based templates; `IC` annotated as a return-autocorrelation proxy. (#62)

### Removed

- Dead code (`alternative_bars`, `get_sector_win_rates`, `to_context_str`,
  deprecated prompt constants) and a no-op `_sector_calibration` dimension. (#60)

## [2.0.0] — AI-first autonomous agent architecture

Major architecture upgrade: the platform moves from a linear
data → analysis → prediction → strategy pipeline to an **AI-first autonomous agent**
centered on an OODA decision loop, fed by a market-intelligence pipeline, quant
signals, and a smart stock screener, with an event-driven Redis-Streams backbone.
Still a **simulation-only toy project** — no live order routing; see the disclaimer
in `README.md`.

### Added

- **Autonomous agent loop** (`src/agent_loop/`) — OODA cycle: signal aggregation →
  Bayesian prescreen → bull/bear debate (urgency-tiered) → risk gates → Kelly position
  sizing → trade proposal. Includes a 7-team `InvestmentDirector`, sentiment-cycle
  emotion gates, thesis/conviction tracking, T+1/T+3/T+5 outcome tracking, and a
  confidence calibrator that learns from outcomes. An always-on daemon
  (`src/agent_loop/daemon/`, `openclaw/`) drives it on the trading calendar.
- **Market intelligence pipeline** (`src/intelligence/`, `src/intelligence_hub/`) —
  5-layer source hierarchy, 7-component content scoring, causal impact chains
  (YAML templates + LLM fallback), a multi-perspective debate engine, and a
  NetworkX-backed temporal knowledge graph.
- **Quant & event bus** (`src/quant/`, `src/event_bus/`) — 3-state HMM regime detector
  (hmmlearn), declarative YAML signal library, optional Qlib Alpha158, and a Redis
  Streams event bus (7 streams / consumer groups) for event-driven micro-OODA cycles.
- **Risk & execution** (`src/risk/`, `src/trading/`) — circuit breaker, VaR/CVaR,
  Kelly sizing, kill switch, layered execution gates, and an A-share constraints engine
  (T+1, board price limits, 100-share lots) — all simulation-only.
- **Smart stock recommendation** (`src/recommendation/`) — multi-style screener with
  sector-relative scoring, an LLM review agent, T+1 overnight-risk quantification,
  SQLite-backed performance tracking, a user-facing Recommendations UI, and a feed into
  the agent loop's signal aggregator.
- **Web/UI** — new pages (ControlTower, Portfolio, Recommendations, Review, SignalDetail,
  AiNews, Watchlist) and 40+ `/api/v1` endpoints; real-time price layering
  (WebSocket → SSE → polling).
- **LLM gateway** (`src/llm/`) — caller-attributed routing with cost/quality/hybrid
  strategies, in-flight dedup, audit logging, consensus voting, and a Claude Code bridge
  fallback (no API key needed).

### Changed

- Data layer hardened with health-aware multi-source fallback chains (EastMoney push2
  via curl_cffi → QMT → Sina → Xueqiu → adata) and a trading-calendar guard.
- `requirements.txt` adds hmmlearn, networkx, scikit-learn, pytest-asyncio, and more.

### Removed

- The legacy rule-based `recommendation` flow's `SessionStrategyRouter` (superseded by
  the agent loop's time-of-day mission routing).

### Fixed

- 32 inherited stale test assertions corrected to current behaviour (model names,
  config defaults, Chinese→English prompt text, API signatures) — no behavioural changes.
- Added the missing `pytest-asyncio` dependency so async tests actually run.

### Security

- All credentials remain env-only (`.env`); no upstream private state, session logs,
  or internal docs are included in this public history.

## [0.1.0] — Initial public release

First open-source release of the A-share AI analysis platform. This is a personal
learning / technical-exploration **toy project** — see the disclaimer in `README.md`.

### Features

- **Data layer** — A-share market data via AKShare (quotes, OHLCV, dragon-tiger list,
  limit-up pool, fund flow), with an optional self-hosted EastMoney proxy for
  VPN-restricted environments.
- **Analysis layer** — technical indicators (MA/MACD/RSI/KDJ/Bollinger), candlestick
  pattern detection, support/resistance, and a Bayesian multi-signal fusion engine.
- **Prediction layer** — LLM-powered analysis and prediction (Gemini, optional Qlib),
  enhanced multi-source prediction, and AI strategy interpretation.
- **Strategy & backtest** — strategy lab with natural-language strategy creation,
  T+1-aware backtesting, paper trading signals, and quant factor analysis.
- **Agent loop** — LLM-driven autonomous research/decision loop (the model is the agent,
  the code is the harness).
- **Web app** — FastAPI backend + React frontend dashboard.
- **Research workstation** — multi-model research pipeline (`./research.sh`):
  Gemini (sentinel) + Qlib (actuary) + Claude (decision brain).

### Security

- All credentials are read from environment variables (`.env`, see `.env.example`);
  no secrets are committed.
