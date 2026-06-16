# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
