# Documentation

A map of the project documentation. Start with the development guide.

## Guides

- [Development Guide](guides/development-guide.md) — architecture, tech stack, data
  flow, module layout, and conventions. **Start here.**
- [Runbook](guides/runbook.md) — local setup, environment, and how to run the stack.
- [Quick Reference](guides/ref/quick-ref.md) — compressed reference card.

## Testing

- [Test Strategy](testing/test-strategy.md) — overall testing approach.
- [Test Cases](testing/test-cases.md) — functional test matrix.
- [QA Test Cases](testing/qa-test-cases.md) — API/endpoint QA matrix.
- [E2E](testing/e2e.md) — end-to-end test execution guide.

## Results

- [v2 Backtest Results](backtest-v2-results.md) — honest out-of-sample evaluation of the
  v2 signal/sizing stack (2019–2024, 14 A-shares). Reproduces with
  [`scripts/backtest_v2_universe.py`](../scripts/backtest_v2_universe.py).

## Components

- [Research Workstation](research-workstation-README.md) — the multi-model research
  pipeline (`./research.sh`): Gemini (sentinel) + Qlib (actuary) + Claude (decision brain).

---

See also the repository root: [`README.md`](../README.md),
[`CONTRIBUTING.md`](../CONTRIBUTING.md), [`CHANGELOG.md`](../CHANGELOG.md),
[`SECURITY.md`](../SECURITY.md).
