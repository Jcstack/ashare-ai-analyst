# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
