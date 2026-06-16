# Quick Reference
<!-- Token-optimized. →=leads to, |=or, +=and, ×=multiples of -->

## DI Pattern
factory: `@lru_cache` in `src/web/dependencies.py` → `Depends()` injection
new svc: add `get_X()` factory, accept deps as ctor params, compose in factory
never: instantiate services directly in route handlers

## Routes
registry: `src/web/routes/api_v1/__init__.py` (all `include_router()` calls)
new route: create file in `routes/api_v1/`, register in `__init__.py` w/ prefix
prefix: set in `__init__.py`, NOT in router file

## Schemas
location: `src/web/schemas/<domain>.py`, re-export from `__init__.py`
base: `BaseModel` | `VersionedSchema` (versioned schemas)

## Modules
structure: `src/<domain>/__init__.py` + `config/<domain>.yaml`
config loader: `src/utils/config.py`
domains: agents, risk, quant, intelligence, audit, workflow, market_intelligence, recommendation

## Agent Tools
registry: `src/web/services/tool_registry.py` via `register()`
each tool: name + description + params schema + handler fn
whitelists: `config/agents.yaml` (per-agent tool permissions)

## A-Share Constants
T+1 | limits: main ±10%, ChiNext/STAR ±20% | stamp: 0.1% sell-only
commission: 0.03% both ways min ¥5 | lot: ×100 shares
hours: Mon-Fri 09:30-15:00 CST | Rf: 2.5%

## Data Layer
pipeline: Data(`src/data/`) → Analysis(`src/analysis/`) → Prediction(`src/prediction/`) → Strategy(`src/strategy/`)
akshare: all calls via `_call_akshare()` | `_bypass_proxy()`, interval ≥ 0.5s
eastmoney proxy: `em_api_call(fn, *args)` — try direct first, on connection failure activate `akshare-proxy-patch` (global monkey-patch) + retry; once active all `_em` calls route through gateway
eastmoney client: `src/data/eastmoney_client.py` — `EastMoneyClient` via curl_cffi Chrome TLS + auth gateway proxy (isolated, no monkey-patch); includes f100=行业; concurrent pages (8 workers, 59 pages in ~2s)
realtime chain: QMT(xtdata,<1s) → Sina(batch) → Xueqiu(batch,session) → adata(batch)
qmt adapter: `src/data/qmt_adapter.py` — `QmtDataAdapter`, `get_qmt_adapter()` DI singleton
qmt broker: `src/web/services/qmt_broker.py` — `QmtBroker(BrokerInterface)`, mode=qmt
ws push: `/api/v1/market/ws` → `useRealtimeWS` hook (WS→SSE→HTTP fallback)
singleton: `get_realtime_quote_manager()` shared across REST + SSE + WS

## AKShare Column Gotcha
`stock_board_concept_name_em()` — verify `df.columns` before mapping!
code=板块代码(NOT 代码) | name=板块名称(NOT 名称) | pct=涨跌幅(NOT 板块涨跌幅) | amt=总市值(NOT 成交额)

## Concept Board
join: CoreConception(numeric "1222") + AKShare(BK-prefix "BK0729") → name_map primary path
filter: IS_PRECISE="0" → drop | "1"|null → keep
noise: `_NOISE_CONCEPT_NAMES` blocklist
push2 down → empty concepts → frontend shows "行情数据暂不可用"

## Frontend
stack: React 19 + TS + Vite + shadcn/ui + TW4
state: React Query (server) + Zustand (client) — never duplicate
api: `frontend/src/api/<domain>.ts` | types: `frontend/src/types/<domain>.ts`
theme: dark default, `:root`=dark `.light`=override
market colors: CSS vars only (`text-market-up`/`text-market-down`), never hardcode hex
polling: `GlobalRealtimePoller` → React Query cache, 10s interval

## Testing
mock: only externals (AKShare, Anthropic, HTTP, File I/O), never internals
fastapi: `app.dependency_overrides[get_X] = lambda: mock` (NOT `patch()`)
fixtures: `pytest.tmp_path` for files, `:memory:` SQLite for DB

## Market Intelligence (v20.0)
module: `src/market_intelligence/` — 16 files
schema: `src/web/schemas/market_signal.py` — MarketSignal envelope + enums
routes: `src/web/routes/api_v1/market_intelligence.py` — 9 endpoints under `/market-intelligence/`
pipeline: SignalBus → ConfirmationGate → ConfidenceScorer → RiskOverlay → PhaseEngine → NotificationOrchestrator → Dispatch
DBs: `data/signals.db` (signal_store), `data/notification_log.db` (notification_log)
config: `config/phases.yaml` (8-phase rules), `config/signal_rules.yaml` (L1-L4 rules)
celery: `openclaw/tasks/signal_scan.py` (backfill, phase_check, digest, cleanup)

## Smart Recommendation (v28.0)
module: `src/recommendation/` — models, screener, review_agent, rec_store, session_strategies
config: `config/recommendation.yaml` — 6 styles, 5 sessions, screening thresholds
routes: `src/web/routes/api_v1/recommendations.py` — 9 endpoints under `/recommendations/`
service: `src/web/services/recommendation_service.py` — orchestrates screen → review → persist → notify
DI: `get_rec_store()`, `get_stock_screener()`, `get_review_agent()`, `get_session_strategy_router()`, `get_recommendation_service()`
DB: `data/recommendations.db` (recommendations + recommendation_outcomes + user_feedback)
celery: `recommendation_pipeline` (every 30 min), `recommendation_cleanup` (daily 18:30), `recommendation_backfill` (daily 16:45)
schema: `InvestmentStyleConfig` in `src/web/schemas/user_config.py`
frontend: `Recommendations.tsx` page, `RecommendationCard`, `RecommendationDetailDialog`, `PerformanceDashboard`, `InvestmentStyleSettingsTab`

## LLM Result Cache (I-068)
module: `src/llm/cache.py` — `LLMResultCache` (L1 in-process + L2 Redis)
DI: `get_llm_result_cache()` → injected into `get_realtime_analyzer()`, `get_sentiment_report_generator()`
Redis keys: `llm:result:<cache_key>` (isolated namespace)
prewarm: `openclaw/tasks/llm_prewarm_pipeline.py` — 3 tasks (market_overview, sentiment_report, hot_stocks)
config: `config/openclaw.yaml` beat_schedule (prewarm_market_overview, prewarm_sentiment_report, prewarm_hot_stocks_preopen)
degradation: Redis down → pure memory (same as pre-cache)

## LLM Routing
module: `src/llm/` — base, router, gateway, google (SDK: `google-genai>=1.0`)
config: `config/llm.yaml` — providers(google only), grounding, caller_model_map, personas
chain: caller → `LLMGateway`(dedup+audit+grounding+caller→model) → `LLMRouter`(provider fallback) → `GoogleProvider`(model fallback)
SDK: `google-genai` (Client-based, NOT deprecated `google-generativeai`)
**SDK gotcha**: `types.Content(parts=...)` requires `types.Part` objects, NOT bare strings (Pydantic validation)
all Gemini callers unified on `gemini-2.5-flash` (default); deep analysis → Claude Code personas via bridge
auto-route: keyword match + length gate → Claude Code; strong keywords (深度分析 etc.) bypass length gate; weak keywords need stock code/name/intent phrase
Claude Code fallback: bridge unavailable → `_send_gemini_with_persona()` (Gemini tool loop + persona overlay)
grounding: Gateway auto-enables Google Search for configured callers (`grounding.enabled_callers` in llm.yaml)
  L1: search_intel (local) → L2: Grounding (complete() only) → L3: ddgs (agent tool loop) → L4: Claude Code WebSearch
  grounded callers: review_agent, trading_advisor, sentiment_report, conversation_service, holiday_research, intel_analysis
  NOT grounded: agent tool loop (has 20+ structured tools), realtime_analyzer, sentiment (data-only)
caller_model_map: empty (all use default); mechanism retained for future per-caller overrides
model fallback: `GoogleProvider(fallback_model="gemini-2.0-flash")` — on primary failure, auto-retry w/ fallback
timeout: 60s per API call, 2 retries per model, Celery soft=300s hard=360s

## Discord Bot (v30.0)
module: `src/discord_bot/` — bot.py, config.py, services.py, cogs/, embeds/
config: `config/discord.yaml` — token_env, guild_id_env, channel_id_env, push_types, colors
entry: `python -m src.discord_bot` (standalone process, shares DI singletons with FastAPI/Celery)
docker: `discord-bot` service in `docker-compose.yaml`
env: `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `DISCORD_CHANNEL_ID`
slash commands: /stock, /quote, /market, /recommend, /flow, /portfolio, /intel, /ask
push: Redis `notifications:push` → cog dispatches to single channel (V1)
NL: `classify_message()` in `cogs/natural_language.py` — symbol detection + keyword routing
agent: /ask creates Discord thread → maps to AgentService thread (in-memory, lost on restart)
sync services: `asyncio.to_thread()` | AgentService: direct `await`

## Research Workstation
module: `src/data/sentinel_capture.py` + `src/prediction/qlib_adapter.py` + `scripts/data_aggregator.py`
config: `config/research.yaml` — sentinel/actuary/decision_brain/bayesian_fusion/ashare_constraints/workspace
skill: `/deep-research {symbol}` — 1000+ char Chinese deep research report + MCP enrichment (step 5)
orchestration: `./research.sh [--symbols X] [--skip-sentinel] [--skip-qlib]`
celery: `research_pipeline.py` (sentinel_capture every 30min, research_aggregate 15:35)
protocol: `.claude/rules/research_protocol.md` — three-model architecture SOP
degradation: Full(3-source) → No-Qlib → No-Gemini → Technical-only → Template-report
Qlib: optional (`_HAS_QLIB` guard), all methods return None/empty when absent
workspace: `workspace/` (gitignored) — signals, reports/deep, sentinel, cache, logs; `get_workspace_dir(sub)`
MCP bridge: `mcp_server/` — 8 read-only tools via `.mcp.json`, stdio transport, Docker API data enrichment

## Deployment
server: gunicorn + uvicorn.workers.UvicornWorker, 2 workers
worker recycling: `--max-requests 10000 --max-requests-jitter 5000` (staggered, always ≥1 alive)
timeout: `--timeout 120 --graceful-timeout 30 --keep-alive 30`
colima: `colima start --cpu 4 --memory 4` (4 GiB required for dual workers)

## Key Files
DI singletons: `src/web/dependencies.py` (incl. `get_qmt_adapter()`)
route registry: `src/web/routes/api_v1/__init__.py` (incl. `ws_market`)
tool registry: `src/web/services/tool_registry.py`
agent config: `config/agents.yaml`
agent DB: `data/agent.db` (SQLite: threads, messages, trades, recommendations, user_config)
lineage DB: `data/lineage.db`
intelligence DB: `data/intelligence.db`
memory DB: `data/memory.db`
signals DB: `data/signals.db` (v20.0 signal store + outcomes)
