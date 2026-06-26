# 🧪 A股智能分析平台 · A-Share AI Analysis Platform

<p align="center">
  <a href="https://github.com/Jcstack/ashare-ai-analyst/actions/workflows/ci.yml"><img src="https://github.com/Jcstack/ashare-ai-analyst/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Jcstack/ashare-ai-analyst/actions/workflows/codeql.yml"><img src="https://github.com/Jcstack/ashare-ai-analyst/actions/workflows/codeql.yml/badge.svg" alt="CodeQL"></a>
  <a href="https://github.com/Jcstack/ashare-ai-analyst/actions/workflows/gitleaks.yml"><img src="https://github.com/Jcstack/ashare-ai-analyst/actions/workflows/gitleaks.yml/badge.svg" alt="Secret scan"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.13-blue.svg" alt="Python 3.13">
  <img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs welcome">
</p>

> **⚠️ 免责声明 / DISCLAIMER**
>
> **本项目仅为个人学习与技术探索的玩具项目（Toy Project）。**
> 所有分析结果、预测信号、评分及任何输出**均不构成任何形式的投资建议或交易决策依据**。
> 作者不对任何因参考本项目内容而产生的投资损失承担责任。**股市有风险，投资须谨慎。**
>
> **This is a personal hobby / toy project for learning and experimentation only.**
> All analysis results, prediction signals, scores, and any output **do NOT constitute investment advice or trading recommendations of any kind**.
> The author assumes no responsibility for any financial loss resulting from using this project.
> **Investing involves risk. Always do your own research.**

---

## 简介 · Introduction

一个基于大语言模型（LLM）驱动的 A 股市场智能分析平台。用 AI 探索 A 股市场的信号分析、新闻情报、量化回测与自主决策循环——纯粹出于对技术的好奇心。

An LLM-powered intelligent analysis platform for the A-share (Chinese stock) market. Built out of curiosity to explore how AI models can be applied to signal analysis, news intelligence, quantitative backtesting, and autonomous agent loops.

---

## 功能特性 · Features

| 模块 | 说明 | Module | Description |
|------|------|--------|-------------|
| 🧠 自主 Agent 循环 | OODA 循环：信号聚合 → 贝叶斯预筛 → 多空辩论 → 风险闸门 → Kelly 仓位（**仅模拟**） | Autonomous Agent Loop | OODA cycle: signal aggregation → Bayesian prescreen → bull/bear debate → risk gates → Kelly sizing (**simulation only**) |
| 📡 市场情报管线 | 5 层信源 + 7 维评分 + 因果影响链 + NetworkX 知识图谱 | Market Intelligence | 5-layer sources + 7-dimension scoring + causal impact chains + NetworkX knowledge graph |
| 🎯 智能选股 | 多风格量化筛选 + LLM 复核 + T+1 隔夜风险 + 胜率追踪 | Smart Stock Picks | Multi-style screener + LLM review + T+1 overnight risk + win-rate tracking |
| 📊 市场状态识别 | HMM 三态（牛 / 熊 / 震荡）+ 情绪周期闸门 | Regime Detection | 3-state HMM (bull / bear / consolidation) + sentiment-cycle gating |
| 🤖 多模型 AI | Claude / Gemini / OpenAI / DeepSeek 路由 + 共识投票 | Multi-LLM | Claude / Gemini / OpenAI / DeepSeek routing + consensus voting |
| 🌊 事件总线 | Redis Streams 事件驱动微 OODA（行情 / 新闻 / 情绪 / 信号） | Event Bus | Redis-Streams event-driven micro-OODA (market / news / sentiment / signal) |
| 🛡️ 风险引擎 | 熔断器 + Kelly 仓位 + VaR + A股约束（T+1 / 涨跌停 / 100 股） | Risk Engine | circuit breaker + Kelly sizing + VaR + A-share constraints (T+1 / price limits / 100-share lots) |
| 🌐 全球情报 + 新闻 | 全球指数 / 大宗 / 汇率关联 + AI 新闻聚合 | Global Intel + News | global indices / commodities / FX correlation + AI news aggregation |
| 📈 量化回测 | backtrader 策略回测，可选 Qlib 自定义 alpha 因子 | Backtesting | backtrader strategy backtesting, optional Qlib custom alpha factors |
| 📱 Discord | 交易信号 / 情报自动推送到 Discord | Discord | auto-push trade signals / intel to Discord |
| 🖥️ Web UI | FastAPI + React 19：ControlTower / Portfolio / Recommendations / Review | Web UI | FastAPI + React 19: ControlTower / Portfolio / Recommendations / Review |
| ⚙️ 自动化调度 | Celery 45+ 定时任务 + 常驻 agent 守护进程 | Automation | Celery beat (45+ tasks) + always-on agent daemon |

---

## 架构 · Architecture

v2 架构以「自主 Agent OODA 循环」为中心，由三路信号来源驱动，下游接风险闸门与（模拟）执行：

```
数据层 / Data  (src/data/)
AKShare · EastMoney push2 · QMT · 多源健康路由回退
      │  行情 / OHLCV / 资金流 / 交易日历
      ▼
┌──────────────────────── 信号来源 / Signal Sources ────────────────────────┐
│  市场情报 Intelligence      量化 Quant             智能选股 Recommendation   │
│  src/intelligence(_hub)/    src/quant/             src/recommendation/      │
│  5层信源·7维评分·因果链·知识图谱  HMM状态·Alpha·信号库    多风格筛选·LLM复核·T+1风险 │
└─────────────────────────────────────┬──────────────────────────────────────┘
      │  signals
      ▼
自主 Agent 循环 / Agent OODA Loop  (src/agent_loop/)
SignalAggregator → DecisionPipeline（贝叶斯预筛 · 多空辩论 · 风险闸门 · Kelly 仓位）
InvestmentDirector（7 团队）· 情绪周期闸门 · ThesisTracker · OutcomeTracker → 置信度校准
      │  TradeProposal  （⚠️ 仅模拟 / simulation only）
      ▼
风险 & 执行 / Risk & Execution               事件总线 / Event Bus
src/risk/ 熔断·Kelly·VaR                     src/event_bus/ Redis Streams
src/trading/ 执行闸门·KillSwitch·A股约束        7 streams → 微 OODA（行情/新闻/情绪/信号）

横切 / Cross-cutting:
src/llm/ 多模型网关（Claude/Gemini/OpenAI/DeepSeek + 共识投票）
src/web/ FastAPI  ·  frontend/ React SPA  ·  src/discord_bot/  ·  openclaw/ Celery + 常驻 daemon
```

---

## 技术栈 · Tech Stack

| 层 / Layer | 技术 / Technologies |
|-----------|-------------------|
| 数据 / Data | AKShare, adata, EastMoney push2 (curl_cffi), QMT/XtQuant (optional), pandas, numpy, pyarrow, yfinance |
| 分析 / Analysis | ta (technical indicators), plotly, matplotlib |
| AI 预测 / AI | Anthropic Claude, Google Gemini, OpenAI, DeepSeek, Claude Code bridge (fallback) |
| 量化 & Agent / Quant | hmmlearn (HMM 市场状态), networkx (知识图谱), scikit-learn, Qlib custom alpha factors (optional) |
| 策略回测 / Backtest | backtrader, Qlib (optional) |
| 后端 / Backend | FastAPI, uvicorn, Redis (cache + Streams 事件总线), Celery + Beat |
| 前端 / Frontend | React 19, TypeScript, Vite, shadcn/ui, Tailwind CSS 4, React Query |
| 通知 / Notification | Discord (bot + webhook) |
| 基础设施 / Infra | Docker Compose, nginx, searxng (self-host search, optional) |

---

## 快速开始 · Quick Start

### 0. 30 秒离线演示 / Try it in 30s (no Docker, no API keys, no network)

```bash
pip install -r requirements.txt
make demo      # 用样例数据跑 v2 回测 / runs the v2 backtest on bundled sample data
```

See [`docs/how-it-works.md`](docs/how-it-works.md) for what it does. For the full
stack (web UI, agent loop, automation), continue below.

### 前置条件 / Prerequisites

- Docker & Docker Compose
- 至少一个 LLM API Key（Anthropic / Google / OpenAI）
- （可选）Discord Bot Token，用于推送通知

### 1. 克隆并配置环境变量 / Clone & configure

```bash
git clone https://github.com/Jcstack/ashare-ai-analyst.git
cd ashare-ai-analyst
cp .env.example .env
# 编辑 .env，填入你的 API Key
# Edit .env and fill in your API keys
```

### 2. 配置关注股票 / Configure watchlist

```bash
# 编辑 config/stocks.yaml，添加你关注的 A 股代码
# Edit config/stocks.yaml to add your A-share stock codes
```

### 3. 启动服务 / Start services

```bash
make up       # Docker 构建 + 启动所有服务 / Build + start all services
```

访问 / Visit: `http://localhost`

### 4. 验证 / Verify

```bash
make logs     # 查看服务日志 / View logs
```

---

## 本地开发 · Local Development

```bash
# Python 后端
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 代码检查 / Lint
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/

# 单元测试 / Unit tests (external deps mocked; this is what CI runs)
.venv/bin/pytest tests/unit -q

# 前端 / Frontend
cd frontend
npm install
npx tsc --noEmit   # 类型检查 / Type check
npm run build
npm run dev        # 开发模式 / Dev mode
```

---

## 配置文件 · Configuration

| 文件 / File | 用途 / Purpose |
|------------|---------------|
| `config/stocks.yaml` | 股票自选池 / Stock watchlist |
| `config/llm.yaml` | LLM 模型路由（调用方→模型映射）/ LLM model routing (caller→model) |
| `config/agent.yaml` · `config/trading_loop.yaml` | Agent / OODA 循环参数 / Agent & OODA-loop params |
| `config/recommendation.yaml` | 智能选股风格/过滤/权重 / Screener styles, filters, weights |
| `config/intelligence_hub.yaml` · `config/event_bus.yaml` | 情报信源 / 事件总线 / Intel sources & event bus |
| `config/risk.yaml` · `config/trading_constraints.yaml` · `config/broker.yaml` | 风险 / A股约束 / 券商 / Risk, A-share constraints, broker |
| `config/openclaw.yaml` | Celery beat 定时任务 / Celery beat schedule |
| `.env` | API Keys 与密钥（**不提交**！）/ API keys (**never commit**!) |

---

## 项目结构 · Project Structure

```
.
├── src/
│   ├── data/              # 多源行情采集 / Multi-source market data (AKShare·EastMoney·QMT)
│   ├── intelligence/      # 市场情报：因果链·辩论·知识图谱 / Causal chains, debate, knowledge graph
│   ├── intelligence_hub/  # 信源聚合·7维评分·存储 / Source aggregation, scoring, store
│   ├── agent_loop/        # 自主 OODA 决策循环 (+ daemon/) / Autonomous OODA loop
│   ├── quant/             # HMM 状态·Alpha·信号库 / HMM regime, alpha, signal library
│   ├── recommendation/    # 智能选股引擎 / Smart stock screener + LLM review
│   ├── trading/           # 执行闸门·A股约束·KillSwitch / Execution gates, constraints
│   ├── risk/              # 熔断·Kelly 仓位·VaR / Circuit breaker, sizing, VaR
│   ├── event_bus/         # Redis Streams 事件总线 / Event bus
│   ├── prediction/        # LLM 分析与预测 / LLM analysis & prediction
│   ├── analysis/          # 技术指标·情绪 / Technical indicators, sentiment
│   ├── llm/               # 多模型网关 / Multi-LLM gateway + router
│   ├── web/               # FastAPI 后端 / FastAPI backend
│   ├── discord_bot/       # Discord 机器人 / Discord bot
│   └── strategy/ backtest/ market_intelligence/ audit/ …
├── frontend/              # React 19 SPA (ControlTower / Portfolio / Recommendations / Review …)
├── openclaw/              # Celery 任务 + 常驻 daemon / Celery tasks (45+) + always-on daemon
├── config/                # YAML 配置文件 / YAML config files
├── mcp_server/            # MCP 数据桥 / MCP data bridge
├── research/              # 研究工作站 / Research workstation
├── tests/                 # 测试 / Tests
├── docs/                  # 文档 / Documentation
├── docker-compose.yaml
└── .env.example
```

---

## 文档 · Documentation

- [`docs/`](docs/README.md) — documentation index
- [`docs/how-it-works.md`](docs/how-it-works.md) — **how the agent works + what the backtest taught us** (newcomer overview)
- [`docs/guides/development-guide.md`](docs/guides/development-guide.md) — architecture, tech stack, data flow (**start here**)
- [`docs/guides/runbook.md`](docs/guides/runbook.md) — local setup & run
- [`docs/backtest-v2-results.md`](docs/backtest-v2-results.md) — **honest out-of-sample backtest of the v2 stack** (spoiler: no demonstrated alpha vs buy-and-hold)
- [`docs/testing/`](docs/testing/test-strategy.md) — test strategy & cases
- [`docs/research-workstation-README.md`](docs/research-workstation-README.md) — research workstation usage

---

## 用 Claude Code 开发 · Develop with Claude Code

This repo is built to be picked up efficiently with [Claude Code](https://claude.com/claude-code)
(or any AI coding agent). It ships project context and ready-made commands:

- [`CLAUDE.md`](CLAUDE.md) — project memory loaded into context automatically: stack,
  architecture, setup, commands, conventions, and gotchas. **Read this first.**
- [`.claude/commands/`](.claude/commands/) — project slash commands: `/verify`, `/lint`,
  `/test` run the exact checks CI gates on.
- [`.claude/settings.json`](.claude/settings.json) — shared, secret-free settings (a safe
  read/test command allowlist so you get fewer permission prompts). Personal overrides go
  in `.claude/settings.local.json` (git-ignored).
- [`research/CLAUDE.md`](research/CLAUDE.md) — a separate analyst-persona project root:
  `cd research && claude`.

```bash
# from the repo root
claude            # start a session; CLAUDE.md context loads automatically
> /verify         # run lint + unit tests + frontend build, the way CI does
```

LLM configuration (Claude via the Claude Code bridge or the Anthropic API, with a Gemini
fallback) lives in [`config/llm.yaml`](config/llm.yaml). Model IDs follow Anthropic's
current catalog (`claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5`).

---

## 社区与开源协作 · Community

- [`LICENSE`](LICENSE) — MIT license
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — contribution and verification expectations
- [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) — community standards
- [`SECURITY.md`](SECURITY.md) — private vulnerability reporting guidance
- [`CHANGELOG.md`](CHANGELOG.md) — release notes
- [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/) — structured bug / feature intake
- [`.github/CODEOWNERS`](.github/CODEOWNERS) — maintainer review ownership

---

## 许可证 · License

MIT License — 自由使用，但请阅读上方免责声明。/ Free to use, but please read the disclaimer above.

---

<p align="center">
  <em>🧪 Toy Project · 玩具项目 · For Learning Only · 仅供学习</em>
</p>
