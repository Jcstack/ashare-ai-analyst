# Contributing

Thanks for your interest in contributing.

## Before you start

- Open an issue first for major features, large refactors, or roadmap changes.
- Never commit secrets, API keys, `.env` files, `data/`, or `reports/`.
- Keep code in English; reports and analysis output should remain in Chinese.
- Prefer focused pull requests that solve one problem at a time.

## Local verification

Run the existing project checks before opening a pull request:

```bash
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/
.venv/bin/pytest tests/ -v --tb=short
cd frontend && npx tsc --noEmit
cd frontend && npm run build
```

## Pull requests

- Fill out the pull request template.
- Include tests when changing behavior.
- Update related documentation when behavior or setup changes.
- Expect maintainer review before merge.

## Security

Please do not open public issues for security vulnerabilities. Follow `SECURITY.md` instead.
