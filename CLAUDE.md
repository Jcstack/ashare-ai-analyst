# CLAUDE.md

Guidance for [Claude Code](https://claude.com/claude-code) and other AI assistants
working in this repository. For full detail, read `docs/guides/development-guide.md`.

## Project

LLM-powered A-share (Chinese stock) market analysis & prediction platform. Personal
learning / technical-exploration toy project — outputs are **not investment advice**
(see the disclaimer in `README.md`).

## Stack

Python 3.13 · FastAPI · React 19 + TypeScript · AKShare · Qlib (optional) · Celery + Redis
· SQLite · Docker Compose. LLM layer: Claude (via the Claude Code bridge or the Anthropic
API) + Google Gemini fallback — configured in `config/llm.yaml`.

## Architecture

`src/data/` → `src/analysis/` → `src/prediction/` → `src/strategy/` + `src/backtest/`

- **Web API** `src/web/` (FastAPI) · **Frontend** `frontend/` (React SPA)
- **Autonomous agents** `src/agents/`, `src/agent_loop/` · **LLM gateway** `src/llm/`
- **Market intelligence** `src/market_intelligence/`, `src/intelligence/`
- **Automation** `openclaw/` (Celery) · **Config** `config/*.yaml`
- **Research workstation** `research/` — a separate Claude Code project root with an
  analyst persona (`cd research && claude`; see `research/CLAUDE.md`)

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in your API keys
cd frontend && npm install
```

## Commands

```bash
# Lint + format (CI gates on these — keep them clean)
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/
# Backend unit tests (fast; external deps are mocked)
.venv/bin/pytest tests/unit -q
# Frontend type-check + build
cd frontend && npx tsc --noEmit && npm run build
# Full stack via Docker
make up        # build + start    ·    make logs    ·    make down
```

## Conventions

- Code and identifiers in **English**; analysis reports and user-facing output in **Chinese**.
- API keys via env vars only (`.env`). **Never commit** `.env`, real tokens/gateways,
  `data/`, `reports/`, or local `.claude/` state.
- Google-style docstrings, type hints on public APIs; `ruff` must be clean.
- AKShare renames DataFrame columns internally — always verify `df.columns` before mapping.
- A-share domain rules matter: T+1 settlement, board price limits (main ±10%,
  ChiNext/STAR ±20%, BSE ±30%), 100-share lots.
- Tests mock only external deps (AKShare, LLM APIs, HTTP) — never internal logic.

## Contributing

Branch → PR → green CI (lint · unit tests · frontend build · secret scan) → squash merge.
`main` is protected. See `CONTRIBUTING.md`.

## Docs

- `docs/guides/development-guide.md` — architecture, data flow (**start here**)
- `docs/guides/runbook.md` — local setup & run
- `docs/testing/` — test strategy & cases
- `docs/research-workstation-README.md` — research workstation usage
