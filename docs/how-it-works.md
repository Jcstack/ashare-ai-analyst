# How It Works — and What We Learned

> ⚠️ **Simulation/research only — not investment advice.** This is a personal
> learning project. See the disclaimer in [`README.md`](../README.md).

A short, honest tour of what this project actually does, how the decision engine
is built, and — crucially — what happened when we backtested it.

## The idea

Most open-source "AI hedge fund" projects are an LLM debate that outputs a
buy/sell. This project asks a different question: *can you put a real
decision-theoretic core under the LLM, specialized for the A-share market?* So
instead of "ask the model and trust it," the v2 engine runs an **OODA loop** with
an explicit, inspectable decision pipeline.

## The decision loop (`src/agent_loop/`)

For each candidate signal, one cycle does:

1. **Aggregate** — collect signals from three independent sources: market
   intelligence (`src/intelligence/`), quant signals (`src/quant/`: HMM regime +
   a signal library), and the smart-stock screener (`src/recommendation/`).
2. **Bayesian prescreen** — a sequential Bayesian belief engine
   (`bayesian_belief.py`) pools per-source log-likelihood-ratios into a posterior
   P(bull). Cheap rejections happen here, *before* any expensive LLM call.
3. **Bull/bear debate** — an LLM debate runs only on signals that survive the
   prescreen. (It can be disabled; buys then degrade gracefully — see #56.)
4. **Risk gates** — circuit breaker, VaR, sentiment-cycle limits, and A-share
   constraints (T+1, board price limits ±10/20/30%, 100-share lots, stamp tax).
5. **Kelly sizing** — fractional-Kelly with volatility targeting
   (`src/risk/position_sizer.py`) turns the posterior + win-rate into a position.

A closed **calibration loop** then tracks each decision's T+1/T+3/T+5 outcome
(`outcome_tracker.py`) and feeds empirical likelihoods back into the Bayesian
engine. The machinery is genuine quant — not prompt-glue.

## The honest part: does it work?

We backtested the deterministic v2 signal/sizing stack out-of-sample on 14
sector-diverse A-shares, 2019–2024. The result:

| Window | Strategy | Buy & Hold | Beat B&H |
|---|---|---|---|
| Full 2019–2024 | **+25.5%** | **+351.7%** | **0 / 14** |

**No demonstrated alpha.** In its current configuration the stack behaves as a
drawdown-limiter that caps trend upside — it captured ~7% of what buying and
holding returned. The full analysis (bull/bear breakdown, per-name table, why,
and the equity-curve chart) is in
[**`docs/backtest-v2-results.md`**](backtest-v2-results.md).

That negative result is the point: it converts the investing thesis from
*asserted* to *measured*, and gives the next change a baseline to beat. Reproduce
it yourself:

```bash
python -m scripts.backtest_v2_universe --start 20190101 --end 20241231 \
    --chart docs/assets/backtest-v2-equity.png
```

## What's real vs. unproven

- **Real:** the Bayesian belief engine, fractional-Kelly sizing, three-method
  VaR/CVaR, the A-share constraint modeling, the HMM regime detector, and the
  test/CI discipline (4,000+ tests). This is engineered software, not a notebook.
- **Unproven:** the *inputs* — likelihood tables, regime priors, and thresholds
  are expert-assigned constants. The backtest above is the first evidence about
  them, and it says they don't yet predict forward returns.

## Where to go next

The backtest points the next work: study the exit rules (the 15% take-profit
dominates the underperformance), fix the empirical likelihood derivation
(`#54`, done), and validate the LLM-debate contribution (`#56`). See
[`ROADMAP.md`](../ROADMAP.md) for the prioritized list.

## Read more

- [`README.md`](../README.md) — features, quick start, architecture diagram.
- [`docs/guides/development-guide.md`](guides/development-guide.md) — full
  architecture and data flow.
- [`docs/backtest-v2-results.md`](backtest-v2-results.md) — the honest results.
