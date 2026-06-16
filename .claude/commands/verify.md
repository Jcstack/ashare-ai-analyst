Run the full local verification the way CI does, and report pass/fail for each step:

1. `.venv/bin/ruff check src/ tests/`
2. `.venv/bin/ruff format --check src/ tests/`
3. `.venv/bin/pytest tests/unit -q`
4. `cd frontend && npx tsc --noEmit && npm run build`

If a step fails, show the failing output and stop. Do not attempt fixes unless I ask.
