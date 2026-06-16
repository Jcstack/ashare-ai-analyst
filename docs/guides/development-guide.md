# Development Guide

Reference document for the A-share analysis platform. For behavioral rules see `CLAUDE.md` and `.claude/rules/`.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│              Cross-cutting: OpenClaw (openclaw/)             │
├──────────────────────────────────────────────────────────────┤
│  Layer 1        Layer 2         Layer 3         Layer 4      │
│  src/data/      src/analysis/   src/prediction/ src/strategy/│
│  AKShare        Indicators      LLM Engine      + backtest/  │
│  Config-driven  Patterns        Claude API      A-Share rules│
├──────────────────────────────────────────────────────────────┤
│  Web: src/web/ (FastAPI)  +  frontend/ (React + TypeScript)  │
└──────────────────────────────────────────────────────────────┘
```

## Tech Stack

See @requirements.txt for Python dependencies and @frontend/package.json for frontend dependencies.

| Layer | Key Technologies |
|-------|-----------------|
| Data | AKShare, adata, XtQuant (QMT), pandas, numpy, Qlib (optional) |
| Analysis | ta (technical indicators), plotly |
| Prediction | Anthropic API (Claude) |
| Strategy | backtrader |
| Web Backend | FastAPI, uvicorn, Redis |
| Web Frontend | React 19, TypeScript, Vite, shadcn/ui, Tailwind CSS 4 |
| Automation | OpenClaw, Celery |
| Infra | Docker Compose, nginx |

## Config Files

| File | Purpose |
|------|---------|
| `config/stocks.yaml` | Watchlist, data collection params, cache settings |
| `config/analysis.yaml` | Indicator params, pattern thresholds |
| `config/openclaw.yaml` | Scheduled tasks, pipeline steps, timeline profiles |
| `config/calendar.yaml` | Trading calendar: sessions, manual overrides |
| `config/global_market.yaml` | Global indices/commodities/currencies symbols + cache TTL |
| `config/keywords.yaml` | Keyword matching rules for news relevance scoring |
| `config/cross_market_map.yaml` | Stock → global market peer mapping (US/HK/commodities) |
| `config/industry_profiles.yaml` | Industry association profiles (9 industries: 影视/航运/白酒/新能源/半导体/医药/银行/地产/汽车) |
| `config/sentinel.yaml` | Data source config + notification channels (wecom/dingtalk/telegram/webhook) + event types |
| `config/agent.yaml` | LLM agent configuration |
| `config/llm.yaml` | LLM provider/model routing config |
| `config/agents.yaml` | Agent registry: per-agent tools, trust zones, LLM settings |
| `config/phases.yaml` | Trading phase definitions + signal rules per phase (v20.0) |
| `config/signal_rules.yaml` | L1-L4 signal rule hierarchy (v20.0) |
| `config/risk.yaml` | Risk engine parameters |
| `config/quant.yaml` | Quant signal library configuration |
| `config/pipelines.yaml` | Pipeline executor config |
| `config/research.yaml` | Research workstation config (sentinel/actuary/decision_brain/fusion/workspace) |
| `config/intelligence.yaml` | Intelligence loop config |
| `config/broker.yaml` | Broker interface config (simulation / qmt / live) |
| `config/trust_zones.yaml` | Agent trust zone definitions |
| `config/policy_sources.yaml` | Policy data source config |

All runtime values loaded via `src/utils/config.py`.

### Config File Descriptions

- **`config/stocks.yaml`**: Stock watchlist and data collection config. Defines stock code lists, date ranges, data frequency, and cache parameters. Users switch analysis targets by editing this file only.
- **`config/analysis.yaml`**: Technical analysis parameter config. Defines indicator calculation parameters (MA periods, MACD params, RSI overbought/oversold thresholds, KDJ params, Bollinger Bands params) and candlestick pattern recognition switches.
- **`config/openclaw.yaml`**: OpenClaw automation schedule config. Defines scheduled task rules (e.g., post-market trigger at 15:30 CST each trading day), Pipeline DAG orchestration (data collection → analysis → prediction → report execution order and dependencies), timeline profiles, and alert/notification channel configuration.
- **`config/industry_profiles.yaml`**: Industry-specific association profiles for holiday research. Each industry defines concept keywords, cross-market peers, and sector-specific analysis focus areas.

### Workspace Directory

All research runtime artifacts live under `workspace/` (gitignored). Helper: `get_workspace_dir(subdir)` in `src/utils/config.py`.

| Subdirectory | Contents |
|---|---|
| `workspace/signals/` | Aggregated fusion signals (`research_signal_*.json`) |
| `workspace/reports/deep/` | `/deep-research` output reports |
| `workspace/reports/weekly/` | Weekly summary reports |
| `workspace/sentinel/` | Sentinel data (`gemini_sense.json`) |
| `workspace/cache/` | Temporary computation cache |
| `workspace/logs/` | Research pipeline logs |

Docker: mounted as `./workspace:/app/workspace` in `api` and `celery-worker` services.

### MCP Data Bridge

`mcp_server/` — read-only MCP server (stdio transport) bridging Claude Code to Docker API analysis data. Auto-discovered via `.mcp.json`.

| Tool | API Path |
|---|---|
| `get_comprehensive_analysis` | `/stock/{symbol}/comprehensive-analysis` |
| `get_bayesian_analysis` | `/stock/{symbol}/indicators/bayesian` |
| `get_realtime_snapshot` | `/stock/{symbol}/realtime-snapshot` |
| `get_fund_flow` | `/stock/{symbol}/fund-flow` |
| `get_recommendations` | `/recommendations/today` |
| `get_market_overview` | `/market/ai-overview` |
| `get_sentiment_data` | `/stock/{symbol}/sentiment` |
| `get_data_health` | `/admin/data-health` |

Config: `ASHARE_API_URL` env var (default `http://localhost:80/api/v1`). Dependencies: `mcp_server/requirements.txt`.

## Data Flow

System data flows follow the pattern: Config-driven → Data Collection → Layer-by-layer Processing → Intelligent Analysis → Strategy Validation.

| Stage | Data Flow Node | Input | Output | Module |
|:------|:---------------|:------|:-------|:-------|
| Stage 1 | YAML Config → AKShare | Config files (stock pool, date range, frequency) | AKShare API request params | Config Loader |
| Stage 2 | AKShare → Raw Data | API request params | Raw OHLCV, financials, fund flow CSV/Parquet files | AKShare Adapter + Data Cache |
| Stage 3 | Raw Data → Preprocessed | Raw data files | Cleaned, adjusted, aligned standard DataFrame | Data Preprocessor |
| Stage 4 | Preprocessed → Analysis | Standard DataFrame | Technical indicator series, candlestick pattern labels, support/resistance levels | Technical Indicators + Patterns |
| Stage 5 | Analysis → Claude Code | Structured analysis data (Prompt template filled) | Trend judgment, confidence, risk level, signals, reasoning chain (CoT) | Prompt Engineering + Claude Engine |
| Stage 6a | Claude Code → Reports | LLM structured output | HTML/Plotly visual analysis reports, signal lists | Report Generator |
| Stage 6b | Claude Code → Backtest | Buy/sell signal sequences | Annualized return, Sharpe Ratio, max drawdown, win rate | A-Share Backtester |

> **Data Integrity Principle**: All analysis and prediction uses only historically published data (Point-in-Time). Look-ahead bias is strictly prohibited. Every data flow record retains timestamps and source identifiers for reproducibility.

## Real-time Quote Architecture

Real-time quotes are served by `RealtimeQuoteManager` (`src/data/realtime.py`) with the following design:

### Multi-source Fallback Chain

```
QMT (xtdata push, <1s)  →  Sina (batch)  →  Xueqiu (batch, session)  →  adata (batch)
```

QMT (XtQuant SDK) is the highest-priority source when installed and connected, providing sub-second latency via local SDK. When QMT is unavailable (Docker, CI, or not installed), the system automatically falls back to the existing AKShare/adata chain. Each source is tried in priority order. On failure, the next source is attempted and health is tracked by `DataSourceRouter`.

### QMT Data Architecture

```
Frontend (WebSocket → SSE → HTTP polling)
    │
DataSourceRouter (QMT → adata → Sina → Xueqiu)
    │
QmtDataAdapter (src/data/qmt_adapter.py)
    ├── xtdata SDK — realtime quotes, minute K, tick, daily OHLCV
    └── xttrader SDK — live order execution (QmtBroker)
```

**Key files:**
- `src/data/qmt_adapter.py` — QmtDataAdapter: xtdata wrapper with symbol conversion
- `src/data/_qmt_column_maps.py` — XtQuant field → project column name mappings
- `src/web/services/qmt_broker.py` — QmtBroker(BrokerInterface): live trading
- `src/web/routes/api_v1/ws_market.py` — WebSocket endpoint for QMT push
- `frontend/src/hooks/useRealtimeWS.ts` — WS→SSE→HTTP fallback hook

**Degradation matrix:**

| Scenario | Data Source | Push Method | Trading |
|----------|-----------|-------------|---------|
| QMT connected | QMT primary | WebSocket | QmtBroker |
| QMT disconnected | AKShare/adata | SSE polling | SimulationBroker |
| QMT not installed | AKShare/adata | SSE polling | SimulationBroker |

### Xueqiu Session Reuse

The Xueqiu fallback uses a persistent `requests.Session` for TCP connection reuse:

1. **Lazy initialization**: Session created on first Xueqiu call via `_ensure_xueqiu_session()`
2. **Cookie prefetch**: `GET https://xueqiu.com/` acquires authentication cookie
3. **Batch API**: All symbols fetched in a single request to `/v5/stock/realtime/quotec.json` (not per-symbol)
4. **Proxy bypass**: `session.trust_env = False` avoids proxy interference

This reduces latency from ~3.5s (6 stocks, per-symbol) to ~0.3s (single batch request).

### Singleton Pattern (Web Layer)

`src/web/dependencies.py` exposes `get_realtime_quote_manager()` as an `@lru_cache` singleton. Both `/market/realtime` (REST) and `/market/stream` (SSE) handlers use this singleton, ensuring the in-memory cache and Xueqiu session are shared across all requests.

### Frontend Global Polling

```
App.tsx
  └── GlobalRealtimePoller (renders null)
        ├── useRealtimeQuotes()   → queryKey: ["realtime-quotes"]
        └── useMarketIndices()    → queryKey: ["market-indices"]
```

- A non-rendering `GlobalRealtimePoller` component in `App.tsx` runs background polling (10s interval) regardless of active page
- All pages (`Dashboard`, `StockDetail`, `Portfolio`) share the same React Query cache via identical `queryKey`
- `AbortSignal` is passed to `fetchRealtimeQuotes` so React Query auto-cancels stale requests when a new polling cycle starts

### WebSocket Push (QMT Active)

WebSocket endpoint (`/api/v1/market/ws`) pushes real-time quotes when QMT is connected (500ms interval). Frontend `useRealtimeWS` hook connects via WS first, falls back to SSE (`/market/stream`), then HTTP polling.

### SSE Fallback

SSE endpoint (`/market/stream`) and `useRealtimeSSE` hook serve as fallback when WebSocket/QMT is unavailable. Global polling (10s) is the final fallback.

## User Level System (v5.0)

The application implements a 3-tier user level model with irreversible "eject" progression, inspired by React's `create-react-app eject`. Level gating is **frontend-only** — all backend endpoints remain available regardless of user level.

### Tier Overview

| Level | Name | Visible Features | Sidebar Nav |
|-------|------|-----------------|-------------|
| L1 | 极简 (Minimal) | AgentResponseCard (conclusion + risk), SimpleWatchlist, PortfolioSummaryCard, MarketBrief | Home, Settings |
| L2 | 结构可见 (Structured) | + Reasoning chain, signal panels, K-line charts, technical indicators, concept details | + Market |
| L3 | 可拼接 (Composable) | + Backtest, factor analysis, Prompt editing, schedule management, all settings | + Strategy, full Settings |

### Key Files

| File | Purpose |
|------|---------|
| `frontend/src/types/user-level.ts` | `UserLevel` type, `EjectState` interface, `DimensionKey` enum |
| `frontend/src/contexts/UserLevelContext.tsx` | Provider, monotonic reducer, localStorage persistence (`user-level-state`), auto-promote logic |
| `frontend/src/components/agent/AgentResponseCard.tsx` | L1 centerpiece — self-contained data fetching, Layer 0/1 display |
| `frontend/src/components/agent/DimensionSignalBar.tsx` | L2+ reasoning dimension bars (technical/capital/sentiment/concept) |
| `frontend/src/components/agent/EjectConfirmDialog.tsx` | Irreversible eject confirmation with ceremony copy |
| `frontend/src/components/settings/AbilitySettingsTab.tsx` | "My Research Abilities" settings tab — shows unlocked abilities + manual eject |

### Level Gating Patterns

**Page-level gating** (hide entire pages):
```tsx
// Sidebar.tsx — filter nav items by level
const navItems = allItems.filter(item => !item.minLevel || level >= item.minLevel);
```

**Component-level gating** (show/hide within a page):
```tsx
// StockDetail.tsx
const { level } = useUserLevel();
{level >= 'L2' && <TabsTrigger value="kline">K线图</TabsTrigger>}
```

**Settings Tab gating**:
```tsx
// Settings.tsx — L1/L2: appearance + notification + ability; L3: all tabs
const visibleTabs = level === 'L3' ? allTabs : basicTabs;
```

### State Rules

- **Monotonic**: Level can only increase (L1→L2→L3), never decrease
- **Auto-promote**: Ejecting any dimension auto-promotes to at least L2; ejecting backtest/factor auto-promotes to L3
- **Persistent**: Stored in `localStorage` under key `user-level-state`
- **Frontend-only**: Backend routes/endpoints are never gated. All 122+ endpoints remain accessible

### Terminology Mapping

A terminology mapping table is maintained for translating quant jargon to plain Chinese, used throughout the agent and UI layers when surfacing explanations to non-expert users.

## Testing

Coverage targets:

| Module | Target |
|--------|--------|
| `src/data/` | ≥ 80% |
| `src/analysis/` | ≥ 85% |
| `src/prediction/` | ≥ 75% |
| `src/strategy/` | ≥ 80% |
| `src/backtest/` | ≥ 85% |
| `src/utils/` | ≥ 90% |

Mock strategy:

| Dependency | Mock |
|------------|------|
| AKShare | `ak.stock_zh_a_hist()` → fixed DataFrame |
| Anthropic API | `client.messages.create()` → preset JSON |
| Xueqiu Session | `_requests.Session` → mock with preset JSON (batch API response) |
| East Money HTTP (CoreConception, push2) | `_get_http_session()` → MagicMock with preset JSON |
| File I/O | `pytest.tmp_path` fixture |

## Research Workstation

Three-model collaborative research pipeline: Sentinel (Gemini) + Actuary (Qlib) + Decision Brain (Claude Code).

### Components

| Component | Module | Description |
|-----------|--------|-------------|
| Sentinel Capture | `src/data/sentinel_capture.py` | News/anomaly/sentiment scanning via Gemini |
| Qlib Adapter | `src/prediction/qlib_adapter.py` | Quantitative prediction (optional, graceful degradation) |
| Data Aggregator | `scripts/data_aggregator.py` | Bayesian fusion of multi-source signals |
| Deep Research Skill | `.claude/skills/deep-research/SKILL.md` | Claude Code `/deep-research` skill |
| Orchestration | `research.sh` | Three-step automation script |
| Celery Tasks | `openclaw/tasks/research_pipeline.py` | Scheduled sentinel capture + aggregation |
| Config | `config/research.yaml` | All parameters (weights, thresholds, constraints) |
| Protocol | `.claude/rules/research_protocol.md` | Three-model architecture SOP |

### Degradation Chain

1. **Full mode**: Sentinel + Actuary + Technical → Bayesian fusion
2. **No Qlib**: Sentinel + Technical → re-weighted
3. **No Gemini**: Actuary + Technical → re-weighted
4. **Minimal**: Technical only → direct Bayesian indicator output

### Quick Start

```bash
# Full pipeline (default symbols from config)
./research.sh

# Custom symbols, skip unavailable sources
./research.sh --symbols 600519,000001 --skip-qlib

# Deep research via Claude Code
/deep-research 600519
```

## Milestones

| Version | Description |
|---------|-------------|
| v0.1.0 | Data layer — config-driven collection + preprocessing |
| v0.2.0 | Analysis layer — indicators + patterns + visualization |
| v0.3.0 | Prediction layer — Claude API analysis + evaluation |
| v0.4.0 | Strategy layer — 3 strategies + backtest engine |
| v1.0.0 | Integration — OpenClaw + full pipeline + Docker + Web UI |

## Concept Board Data Architecture

### Data Flow

```
东方财富 F10 CoreConception API ──┐
(emweb.securities.eastmoney.com)  │  返回: 数字代码 "1222"/"847"
                                  ├──→ ConceptBoardService (TTL 缓存)
AKShare stock_board_concept_*() ──┘  返回: BK 前缀代码 "BK0729"/"BK0847"
(push2.eastmoney.com)                        │
                                             ▼
                                   fetch_stock_concepts(symbol)
                                   = CoreConception 反查 + concept_list dual-key join
                                   = 先尝试 code 匹配 (通常失败), 再尝试 name 匹配 ✓
                                             │
                                             ▼
                                   API: /stock/{sym}/concepts
                                   → StockConceptsResult { concepts, resonance }
```

### AKShare Column Name Mapping (CRITICAL)

`stock_board_concept_name_em()` returns the following columns. **The exact names MUST be used in code** — using wrong column names silently returns empty strings/NaN and is hard to debug:

```
AKShare stock_board_concept_name_em() actual columns:
  排名, 板块名称, 板块代码, 最新价, 涨跌额, 涨跌幅, 总市值, 换手率, 上涨家数, 下跌家数, 领涨股票, 领涨股票-涨跌幅
```

| Our field | Correct column name | ~~Wrong (caused bug)~~ |
|-----------|-------------------|----------------------|
| code | `"板块代码"` | ~~`"代码"`~~ |
| name | `"板块名称"` | ~~`"名称"`~~ |
| pct_change | `"涨跌幅"` | ~~`"板块涨跌幅"`~~ |
| amount | `"总市值"` | ~~`"成交额"`~~ |
| up_count | `"上涨家数"` | (correct) |
| down_count | `"下跌家数"` | (correct) |
| flat_count | _(does not exist)_ | ~~`"平家数"`~~ |

> **Lesson learned**: AKShare column names are NOT the same as the raw East Money API field names. AKShare internally renames columns. Always verify with `df.columns` before writing mapping code. The wrong column names caused ALL concept data to return as empty strings (name="", code=""), which silently broke the entire concept join pipeline.

### API Code Format Mismatch (CRITICAL)

The two East Money APIs use **different code formats** for concept boards:

| API | Example codes | Format |
|-----|--------------|--------|
| CoreConception (`emweb.securities.eastmoney.com`) | `"1222"`, `"847"`, `"590"` | Numeric (no prefix) |
| AKShare concept list (`push2.eastmoney.com`) | `"BK0729"`, `"BK0847"`, `"BK0590"` | BK-prefixed |

**Impact**: Direct code-based join always fails (e.g., `"1222" != "BK0501"`).

**Solution**: `fetch_stock_concepts()` uses **dual-key join** — code_map (fallback) + **name_map (primary path)**:
```python
board = (code_map.get(ci["code"]) if ci["code"] else None) or name_map.get(ci["name"])
```

**Edge case**: Some F10 sub-classification concepts (e.g., "影视院线", "影视动漫制作") exist in CoreConception but NOT in the AKShare concept board list (only "影视概念" exists there). These fall through both code_map and name_map, landing in the zero-value fallback path — this is expected behavior.

### IS_PRECISE Filtering

CoreConception API returns an `IS_PRECISE` field per concept:

| IS_PRECISE | Examples | Action |
|---|---|---|
| `"1"` | AIGC概念, 影视概念, 西部大开发 | **Keep** (precise concept) |
| `null` / missing | 影视院线, 影视动漫制作 | **Keep** (filter noise names) |
| `"0"` | 传媒, 新疆板块, 深股通 | **Filter** (broad industry tag) |

Noise name blocklist (`_NOISE_CONCEPT_NAMES`): 昨日高振幅, 昨日高换手, 昨日连板, 融资融券, 沪股通, 深股通, MSCI中国, 最近多板

### East Money Domain Accessibility

| Domain | Purpose | VPN-accessible | Notes |
|--------|---------|---------------|-------|
| `emweb.securities.eastmoney.com` | F10 CoreConception (stock→concept reverse lookup) | **Always** | Primary data source for per-stock concepts |
| `push2.eastmoney.com` / `79.push2.eastmoney.com` | AKShare concept list + realtime quotes | **Unstable** | Sometimes blocked by VPN DNS (resolves to 198.18.x.x), sometimes works |
| `datacenter.eastmoney.com` | F10 report data (per-stock concepts) | **Always** | `RPT_F10_CORETHEME_BOARDTYPE` works, but no concept list realtime quotes |
| `data.eastmoney.com` | East Money Data Center web pages | **Always** | HTML pages accessible |

When push2 is unreachable, the concept list returns empty → join produces no live data → frontend sees pct_change=0, up_count=0, down_count=0. Frontend components (ConceptMiniCard, ConceptBadgeRow) detect this state and show "行情数据暂不可用" instead of misleading zeros.

## Project Structure

```
ashare-ai-analyst/
├── CLAUDE.md                # Claude Code project instructions
├── requirements.txt         # Python dependencies
├── Dockerfile               # Backend container
├── docker-compose.yaml      # Multi-service orchestration
├── Makefile                 # Docker management (make up/down/rebuild/clean)
├── nginx/                   # nginx.conf for reverse proxy
│   └── nginx.conf
├── config/                  # YAML configuration (all runtime values)
│   ├── stocks.yaml          # Stock watchlist & data config
│   ├── analysis.yaml        # Analysis parameters config
│   ├── openclaw.yaml        # OpenClaw automation schedule + timeline profiles
│   ├── calendar.yaml        # Trading calendar sessions + manual overrides
│   ├── global_market.yaml   # Global indices/commodities/currencies symbols
│   ├── keywords.yaml        # Keyword matching rules for news relevance
│   ├── cross_market_map.yaml # Stock → global market peer mapping
│   ├── industry_profiles.yaml # Industry association profiles (9 industries)
│   ├── sentinel.yaml        # Data sources + notification channels + events
│   ├── agent.yaml           # LLM agent configuration
│   └── llm.yaml             # LLM provider/model routing
├── data/                    # Data storage (not in Git)
│   ├── raw/                 # AKShare raw data (CSV/Parquet) — immutable
│   └── processed/           # Cleaned data + profile_overrides.json + portfolio
├── src/                     # Source code
│   ├── __init__.py
│   ├── data/                # Layer 1: data collection & preprocessing
│   │   ├── __init__.py
│   │   ├── fetcher.py       # AKShare data fetcher with caching
│   │   ├── preprocessor.py  # Data cleaning, adjustment, alignment
│   │   ├── realtime.py      # Real-time quotes (multi-source: Sina → Xueqiu → adata)
│   │   ├── registry.py      # Full A-share stock registry (5000+ stocks)
│   │   ├── news_fetcher.py  # AKShare news fetcher
│   │   ├── concept_board.py # Concept board service (CoreConception + AKShare + TTL cache)
│   │   ├── trend_news.py    # TrendNewsAggregator + KeywordMatcher + ResonanceDetector
│   │   ├── trading_calendar.py # TradingCalendar (chinese-calendar + manual overrides)
│   │   └── global_market.py # GlobalMarketFetcher (yfinance, TTL cache)
│   ├── analysis/            # Layer 2: technical + concept + cross-market analysis
│   │   ├── __init__.py
│   │   ├── indicators.py    # Technical indicators (MA/EMA/MACD/RSI/KDJ/Bollinger/OBV/VWAP)
│   │   ├── patterns.py      # Candlestick pattern recognition
│   │   ├── explanations.py  # Beginner-friendly indicator explanations (Chinese)
│   │   ├── visualizer.py    # Visualization (K-line charts + indicator overlays)
│   │   ├── concept_analyzer.py # ConceptAnalyzer (heat scoring + concept linkage analysis)
│   │   ├── cross_market.py  # CrossMarketAnalyzer (US/HK/commodity peers, impact scoring)
│   │   └── association_graph.py # AssociationProfileBuilder (industry profiles + concept/peer/keyword aggregation)
│   ├── prediction/          # Layer 3: LLM analysis & prediction
│   │   ├── __init__.py
│   │   ├── prompts.py       # Structured prompt templates
│   │   ├── realtime_analyzer.py # Real-time stock analysis + quick insight
│   │   ├── data_validator.py # Prediction data validation
│   │   ├── trading_advisor.py # TradingAdvisor (dual-layer: quant signals + AI judgment)
│   │   └── sentiment_report.py # SentimentReportGenerator (6-part structured report)
│   ├── strategy/            # Layer 4: trading strategies & signal generation
│   │   └── __init__.py
│   ├── backtest/            # Layer 4: A-share rules backtesting framework
│   │   └── __init__.py
│   ├── market_intelligence/  # v20.0 Market Intelligence pipeline
│   │   ├── __init__.py
│   │   ├── signal_bus.py     # SignalBus (asyncio.Queue fan-out) + 3 adapters
│   │   ├── signal_store.py   # SQLite persistence + T+3/T+5 accuracy backfill
│   │   ├── risk_overlay.py   # RiskOverlayEngine (regime + circuit breaker + VaR + macro)
│   │   ├── macro_classifier.py # MacroRegimeClassifier (risk_on/off/neutral)
│   │   ├── confidence_scorer.py # 5-factor weighted composite scorer (0-100)
│   │   ├── confirmation_gate.py # SignalConfirmationGate (per-type confirmation rules)
│   │   ├── phase_engine.py   # 8-phase trading model wrapping TradingCalendar
│   │   ├── notification_orchestrator.py # URGENT/DIGEST/BLOCK/SUPPRESS routing
│   │   ├── notification_log.py # SQLite delivery audit log
│   │   ├── anti_silo.py      # Diversity injection + contrarian views
│   │   ├── signal_rule_engine.py # L1-L4 signal filtering rules
│   │   ├── sector_rotation.py # Sector rotation detection
│   │   ├── correlation_service.py # Correlation matrix + anomaly detection
│   │   ├── data_source_manager.py # Data source health + failover
│   │   └── latency_tracker.py # P50/P95/P99 latency metrics
│   ├── web/                 # FastAPI backend
│   │   ├── app.py           # FastAPI app factory (lifespan + timing middleware)
│   │   ├── dependencies.py  # @lru_cache singleton DI factories (50+ services)
│   │   ├── utils.py         # sanitize_records(), df_to_records()
│   │   ├── schemas/         # Pydantic models split by domain
│   │   │   ├── __init__.py  # Re-exports all models
│   │   │   ├── stock.py     # Stock, watchlist, indicator models
│   │   │   ├── market.py    # Dragon tiger, limit up, market index, global market models
│   │   │   ├── fund_flow.py # Fund flow, support/resistance models
│   │   │   ├── prediction.py # Prediction request/result models
│   │   │   ├── portfolio.py # Portfolio position, diagnosis models
│   │   │   ├── backtest.py  # Backtest request/response, strategy models
│   │   │   ├── analysis.py  # Bayesian, move analysis, chart event models
│   │   │   ├── news.py      # News, anomaly, sentiment models
│   │   │   ├── notification.py # Notification models
│   │   │   ├── admin.py     # API key, usage, routing models
│   │   │   ├── settings.py  # Config update, watchlist models
│   │   │   ├── strategy.py  # NL strategy, AI optimization models
│   │   │   ├── common.py    # ApiResponse, MarketAIOverview
│   │   │   ├── concept.py   # Concept board, heat, constituent models
│   │   │   ├── advisor.py   # Trading advisor models (8 models)
│   │   │   ├── sentiment.py # Sentiment, resonance, cross-market models (12 models)
│   │   │   ├── scheduler.py # Scheduler plans, status models (9 models)
│   │   │   ├── holiday_research.py # Holiday research models (26+ models)
│   │   │   ├── market_signal.py # v20.0 MarketSignal envelope, SignalType, RiskLevel, MarketPhase, PushDecision
│   │   │   ├── user_config.py # UserFollows (8 dimensions) + NotificationPrefs
│   │   │   ├── agent_io.py  # Agent I/O schemas
│   │   │   ├── capital.py   # Capital management schemas
│   │   │   ├── chat.py      # Chat schemas
│   │   │   ├── conversation.py # Conversation schemas
│   │   │   ├── lineage.py   # Lineage schemas
│   │   │   ├── registry.py  # Registry schemas
│   │   │   └── versioning.py # VersionedSchema base class
│   │   ├── routes/api_v1/   # API route handlers (pure routing, Depends() DI)
│   │   │   ├── __init__.py  # Centralized router prefix registration
│   │   │   ├── stocks.py    # Stock CRUD + indicators + S/R + chart events
│   │   │   ├── market.py    # Market indices + calendar + realtime
│   │   │   ├── predictions.py # LLM predictions
│   │   │   ├── portfolio.py # Portfolio CRUD + sync
│   │   │   ├── backtest.py  # Backtesting
│   │   │   ├── backtest_interpret.py # AI backtest interpretation
│   │   │   ├── news.py      # News, anomalies, sentiment, hot rank
│   │   │   ├── notifications.py # Notification CRUD
│   │   │   ├── admin.py     # Admin: keys, usage, schedule status
│   │   │   ├── settings.py  # Config management
│   │   │   ├── search.py    # Stock search
│   │   │   ├── agent.py     # AI agent: analysis, move, quick insight
│   │   │   ├── prompts.py   # Prompt CRUD + test execution
│   │   │   ├── strategy_lab.py # Strategy lab: NL create, optimize, paper trade
│   │   │   ├── concept.py   # Concept board: hot, constituents, history, stock concepts
│   │   │   ├── advisor.py   # AI advisor: advise, holiday impact, pre-opening
│   │   │   ├── sentiment.py # Sentiment: resonance, report, market-pulse, cross-market
│   │   │   ├── scheduler.py # Scheduler: status, plans, override, calendar, sentinel-config
│   │   │   ├── global_market.py # Global market: snapshot, indices, commodities, currencies
│   │   │   ├── holiday_research.py # Holiday research: context, notes, analyze, evidence, scenarios
│   │   │   ├── market_intelligence.py # v20.0: signals, trend/anomaly/sector radar, correlation, macro, timeline, accuracy
│   │   │   ├── chat.py     # Chat endpoints
│   │   │   ├── conversation.py # Conversation endpoints
│   │   │   ├── capital.py  # Capital management endpoints
│   │   │   ├── trades.py   # Trade execution endpoints
│   │   │   └── user_config.py # User follows + notification prefs
│   │   └── services/        # Business logic services
│   │       ├── stock_service.py
│   │       ├── prediction_service.py
│   │       ├── backtest_service.py
│   │       ├── portfolio_service.py
│   │       ├── admin_service.py
│   │       ├── market_service.py          # Market indices + realtime quotes
│   │       ├── strategy_lab_service.py
│   │       ├── strategy_context_service.py
│   │       ├── paper_trade_signal_service.py
│   │       ├── advisor_service.py         # AI trading advisor orchestration
│   │       ├── sentiment_service.py       # Sentiment aggregation + report orchestration
│   │       ├── holiday_research_service.py # Holiday research: data collection + LLM analysis + evidence CRUD
│   │       ├── notification_dispatcher.py # Multi-channel push (wecom/dingtalk/telegram/webhook)
│   │       ├── sentinel_config_service.py # sentinel.yaml read/write
│   │       └── profile_override_service.py # Association profile overrides (JSON file persistence)
│   └── utils/               # Shared utilities — config loader, logger
│       ├── __init__.py
│       ├── config.py        # YAML config loading & saving
│       ├── logger.py        # Logging configuration
│       └── market_hours.py  # Market hours utilities
├── frontend/                # React frontend
│   ├── src/
│   │   ├── api/             # API client layer (stocks, market, portfolio, concept, advisor, sentiment, scheduler, holiday-research)
│   │   ├── components/      # UI components
│   │   │   ├── ui/          # shadcn/ui primitives
│   │   │   ├── agent/       # v5.0 Agent components (AgentResponseCard, DimensionSignalBar, EjectConfirmDialog)
│   │   │   ├── stock/       # Stock detail components (ConceptTagBar, ConceptDetailSheet, ConceptAnalysisTab, CrossMarketCard, HolidayResearchPanel, StockAdvisorCard, etc.)
│   │   │   ├── portfolio/   # Portfolio components (AddPositionDialog, PositionTable, etc.)
│   │   │   ├── dashboard/   # Dashboard components (GlobalMarketPanel, SentimentRadar, SimpleWatchlist, PortfolioSummaryCard, MarketBrief)
│   │   │   ├── settings/    # Settings tabs (NotificationSettingsTab, ScheduleManagementTab, AbilitySettingsTab)
│   │   │   ├── layout/      # Header, Sidebar, NotificationCenter (level-gated)
│   │   │   └── analysis/    # MoveAnalysisPanel, etc.
│   │   ├── contexts/        # React contexts (UserLevelContext — v5.0 level state)
│   │   ├── hooks/           # Custom React hooks (useStocks, usePortfolio, useConcept, useAdvisor, useSentiment, useScheduler, useHolidayResearch, etc.)
│   │   ├── pages/           # Page components (Dashboard, StockDetail, Portfolio, Market, Predictions, Settings)
│   │   └── types/           # TypeScript type definitions (stock, market, portfolio, concept, advisor, sentiment, scheduler, holiday-research, user-level)
│   ├── package.json
│   └── vite.config.ts
├── openclaw/                # OpenClaw integration (automation scheduling)
│   ├── tasks/               # Scheduled task definitions (daily_pipeline, sentiment_pipeline, global_market_pipeline)
│   ├── timeline_scheduler.py # TimelineScheduler (ScheduleProfile enum, should_execute guard)
│   └── hooks/               # Pipeline trigger hooks
├── notebooks/               # Jupyter Notebooks (exploratory analysis)
├── reports/                 # Generated analysis reports (not in Git)
├── tests/                   # Test code
│   ├── conftest.py          # Shared fixtures
│   ├── unit/                # Unit tests (~1956 tests)
│   ├── integration/         # Integration tests
│   ├── e2e/                 # End-to-end tests (planned)
│   └── fixtures/            # Test data files
├── docs/                    # Project documentation
│   ├── guides/              # development-guide.md (this file), runbook.md
│   ├── testing/             # Test strategy, test cases, e2e docs
│   └── research-workstation-README.md  # Research workstation usage
└── static/                  # Static assets
```

## StockDetail Page Layout

Understanding the individual stock detail page layout is critical for test case generation.

### L1 Layout (极简模式)

```
┌─────────────────────────────────────────────────────┐
│ Breadcrumb (智能投顾 > 股票名)       [加自选] [添加持仓] │
├─────────────────────────────────────────────────────┤
│ Price Header Card                                    │
│   RealtimePriceHeader (价格 + 涨跌幅)                 │
├─────────────────────────────────────────────────────┤
│ AgentResponseCard                                    │
│   Layer 0: 结论 + 置信度 + 一句话理由                  │
│   [查看推理过程 ▾] → eject to L2                      │
│   风控免责声明                                        │
└─────────────────────────────────────────────────────┘
```

### L2+ Layout (结构可见/可拼接模式)

```
┌─────────────────────────────────────────────────────┐
│ Breadcrumb (智能投顾 > 股票名)       [加自选] [添加持仓] │
├─────────────────────────────────────────────────────┤
│ AlertBanner (异常提示)                                │
├─────────────────────────────────────────────────────┤
│ Price Header Card                                    │
│   RealtimePriceHeader (价格 + 涨跌幅)                 │
│   ConceptBadgeRow (行业 | 概念badges + 涨跌幅 + 共振)  │
├─────────────────────────────────────────────────────┤
│ PositionContextCard (仅持仓股显示)                     │
├─────────────────────────────────────────────────────┤
│ ComprehensiveAnalysisCard (AI 速览)                   │
├─────────────────────────────────────────────────────┤
│ Tabs: K线图 | 技术指标 | AI投顾 | 概念板块 | 涨跌归因    │
│       资讯研报 | 龙虎榜                                │
│ ┌─────────────────────────────────────────────────┐ │
│ │ K线图 tab:                                       │ │
│ │   Period selector + Range selector               │ │
│ │   CandlestickChart                               │ │
│ │   ChartEventTimeline                             │ │
│ │   grid(2→3): IntradayTrades, S/R, FundFlow       │ │
│ │                                                  │ │
│ │ AI投顾 tab:                                      │ │
│ │   grid(1→2→3): StrategySignal, Advisor, CrossMkt │ │
│ │   HolidayResearchPanel (假期期间)                  │ │
│ │   AIInsightPanel                                 │ │
│ │                                                  │ │
│ │ 概念板块 tab:                                     │ │
│ │   ConceptAnalysisTab (总览+对比表+柱状图+洞察)      │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```
