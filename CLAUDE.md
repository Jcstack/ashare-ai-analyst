# CLAUDE.md

A-share intelligent analysis & prediction platform (LLM-powered).

## Architecture

Data(`src/data/`) → Analysis(`src/analysis/`) → Prediction(`src/prediction/`) → Strategy(`src/strategy/` + `src/backtest/`)

Web: FastAPI(`src/web/`) + React(`frontend/`), Automation: OpenClaw(`openclaw/`), Config: `config/*.yaml`

Research Analyst: `cd research && claude` — independent Claude Code project root with an analyst persona (see `research/CLAUDE.md`)

Tech: AKShare, Qlib (optional), Gemini, Celery+Redis, SQLite

## Documentation

- `docs/guides/development-guide.md` — Architecture, tech stack, data flow (start here)
- `docs/guides/runbook.md` — Local setup & run
- `docs/testing/` — Test strategy, test cases, e2e guide
- `docs/research-workstation-README.md` — Research workstation usage

## Constraints

- Code in English; reports and analysis output in Chinese
- API keys via env vars only; never commit `.env`, `data/`, `reports/`

## Verify

```bash
.venv/bin/ruff check src/ tests/ && .venv/bin/ruff format --check src/ tests/
.venv/bin/pytest tests/ -v
cd frontend && npx tsc --noEmit && npm run build
make up   # Docker clean rebuild
```
