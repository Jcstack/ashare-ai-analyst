Run lint + format + type checks and report results (do not auto-fix unless I ask):

- `.venv/bin/ruff check src/ tests/`
- `.venv/bin/ruff format --check src/ tests/`
- `cd frontend && npx tsc --noEmit`
