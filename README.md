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
| 📊 市场数据 | AKShare / adata 行情采集，自动缓存 | Market Data | AKShare / adata quote collection with caching |
| 🔍 技术分析 | MA、MACD、RSI、KDJ、布林带、K线形态识别 | Technical Analysis | MA, MACD, RSI, KDJ, Bollinger Bands, candlestick pattern recognition |
| 🤖 多模型 AI | Claude / Gemini / OpenAI 多模型路由与共识分析 | Multi-LLM | Claude / Gemini / OpenAI routing and consensus analysis |
| 🧠 自主 Agent | OODA 循环驱动的投资逻辑追踪与决策流水线（仅模拟） | Autonomous Agent | OODA-loop driven thesis tracking & decision pipeline (simulation only) |
| 🌐 全球情报 | 全球指数/大宗商品/汇率/跨市场关联分析 | Global Intel | Global indices / commodities / FX / cross-market correlation |
| 📰 新闻情报 | RSS + 关键词匹配 + LLM 情绪评分 | News Intel | RSS + keyword matching + LLM sentiment scoring |
| 📈 量化回测 | backtrader 策略回测，Qlib 可选集成 | Backtesting | backtrader strategy backtesting, optional Qlib integration |
| 📱 Discord Bot | 自动推送分析报告到 Discord 频道 | Discord Bot | Auto-push analysis reports to Discord channels |
| 🖥️ Web UI | FastAPI + React 19 + TypeScript 前端控制台 | Web UI | FastAPI + React 19 + TypeScript dashboard |
| ⚙️ 自动化调度 | Celery + Redis 定时任务（如收盘后自动分析） | Automation | Celery + Redis scheduled tasks (e.g., post-market auto-analysis) |

---

## 架构 · Architecture

```
数据层 (Data)          分析层 (Analysis)        预测层 (Prediction)      策略层 (Strategy)
src/data/         →   src/analysis/         →   src/prediction/      →   src/strategy/
AKShare/adata         技术指标 / 形态识别         LLM 多模型引擎              + src/backtest/
Config-driven         Indicators / Patterns      Claude/Gemini/OpenAI        A股规则约束

                    横切关注点 / Cross-cutting
          ┌─────────────────────────────────────────────────┐
          │  OpenClaw (openclaw/)  ·  Celery 自动化调度       │
          │  src/web/ FastAPI      ·  frontend/ React SPA    │
          │  src/agents/ 自主智能体  ·  Discord Bot           │
          └─────────────────────────────────────────────────┘
```

---

## 技术栈 · Tech Stack

| 层 / Layer | 技术 / Technologies |
|-----------|-------------------|
| 数据 / Data | AKShare, adata, pandas, numpy, yfinance |
| 分析 / Analysis | ta (technical indicators), plotly |
| AI 预测 / AI | Anthropic Claude, Google Gemini, OpenAI |
| 策略回测 / Backtest | backtrader, Qlib (optional) |
| 后端 / Backend | FastAPI, uvicorn, Redis, Celery |
| 前端 / Frontend | React 19, TypeScript, Vite, shadcn/ui, Tailwind CSS 4 |
| 通知 / Notification | Discord (bot + webhook) |
| 基础设施 / Infra | Docker Compose, nginx |

---

## 快速开始 · Quick Start

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

# 单元测试 / Tests
.venv/bin/pytest tests/ -v

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
| `config/llm.yaml` | LLM 模型路由 / LLM model routing |
| `config/openclaw.yaml` | 定时任务 / Scheduled tasks |
| `config/agent.yaml` | Agent 参数 / Agent parameters |
| `config/analysis.yaml` | 技术指标参数 / Technical indicator params |
| `config/risk.yaml` | 风险引擎参数 / Risk engine params |
| `.env` | API Keys 与密钥（不提交！）/ API keys (never commit!) |

---

## 项目结构 · Project Structure

```
.
├── src/
│   ├── data/            # 数据采集 / Data collection
│   ├── analysis/        # 技术分析 / Technical analysis
│   ├── prediction/      # LLM 预测 / LLM prediction
│   ├── strategy/        # 策略 / Strategy
│   ├── backtest/        # 回测 / Backtesting
│   ├── agents/          # 自主 Agent / Autonomous agents
│   ├── llm/             # 多模型网关 / Multi-LLM gateway
│   ├── web/             # FastAPI 后端 / FastAPI backend
│   ├── discord_bot/     # Discord 机器人 / Discord bot
│   └── ...
├── frontend/            # React 前端 / React frontend
├── openclaw/            # Celery 任务调度 / Task automation
├── config/              # YAML 配置文件 / YAML config files
├── tests/               # 测试 / Tests
├── docs/                # 文档 / Documentation
├── docker-compose.yaml
└── .env.example
```

---

## 文档 · Documentation

- [`docs/`](docs/README.md) — documentation index
- [`docs/guides/development-guide.md`](docs/guides/development-guide.md) — architecture, tech stack, data flow (**start here**)
- [`docs/guides/runbook.md`](docs/guides/runbook.md) — local setup & run
- [`docs/testing/`](docs/testing/test-strategy.md) — test strategy & cases
- [`docs/research-workstation-README.md`](docs/research-workstation-README.md) — research workstation usage

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
