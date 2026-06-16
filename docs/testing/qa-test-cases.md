# QA Manual Test Cases

A-share stock analysis platform manual test cases, organized by PRD domain.

**Document Version**: 1.0.0
**Last Updated**: 2026-02-13
**Total Test Cases**: 90
**Platform Under Test**: A-share Intelligent Analysis & Prediction System v3.2

---

## Conventions

- **Priority**: P0 = Must pass before release, P1 = Should pass, P2 = Nice to have
- **Automatable**: Whether the test case can be converted to an automated API/E2E test
- **Base URL**: `http://localhost:8000/api/v1`
- **Stock codes used in examples**: `000001` (Ping An Bank), `600519` (Kweichow Moutai), `300750` (CATL)

---

## 1. Data Collection (QA-DATA)

| ID | PRD Ref | Preconditions | Steps | Expected Result | Priority | Automatable |
|----|---------|---------------|-------|-----------------|----------|-------------|
| QA-DATA-001 | FR-D001 | `config/stocks.yaml` contains a valid watchlist with at least 3 stocks | 1. Start the backend server. 2. `GET /watchlist` | Response is a JSON array. Each item has `symbol`, `name`, `board`, `close`, `pct_change`. Count matches watchlist size. | P0 | Yes |
| QA-DATA-002 | FR-D002 | Stock `000001` has historical data available via AKShare | 1. `GET /stock/000001/ohlcv?period=daily` | Response is a JSON array of OHLCV records. Each record has `date`, `open`, `high`, `low`, `close`, `volume`. Dates are sorted ascending. No NaN values in response. | P0 | Yes |
| QA-DATA-003 | FR-D003 | Backend is running with StockRegistry loaded | 1. `GET /stocks/search?q=000&limit=10` | Response is a JSON array with up to 10 items. Each item has `symbol`, `name`, `board`. All symbols start with `000`. | P0 | Yes |
| QA-DATA-004 | FR-D003 | StockRegistry loaded | 1. `GET /stocks/search?q=` (empty query) with `limit=20` | Response is a non-empty JSON array (returns popular/default stocks or empty). No server error (HTTP 200). | P1 | Yes |
| QA-DATA-005 | FR-D004 | Market is open or AKShare has cached data | 1. `GET /market/realtime?symbols=000001,600519` | Response is a JSON array with 2 items. Each has `symbol`, `price`, `change`, `pct_change`, `volume`. Prices are positive floats. | P0 | Yes |
| QA-DATA-006 | FR-D005 | Dragon tiger data is available (post-market) | 1. `GET /market/dragon-tiger?start_date=&end_date=` (defaults) | Response is a JSON array (may be empty during trading hours). No 500 error. | P1 | Yes |
| QA-DATA-007 | FR-D006 | Limit up pool data available | 1. `GET /market/limit-up?date=` (defaults to today) | Response is a JSON array. Each item has stock identification fields. No 500 error. | P1 | Yes |
| QA-DATA-008 | FR-D004 | Backend running, stock 000001 exists | 1. `GET /stock/000001/ohlcv?period=5` (5-minute bars) | Response is a JSON array of intraday bars with `date`, `open`, `high`, `low`, `close`, `volume`. Each bar represents a 5-minute interval. | P1 | Yes |

---

## 2. Analysis (QA-ANLYS)

| ID | PRD Ref | Preconditions | Steps | Expected Result | Priority | Automatable |
|----|---------|---------------|-------|-----------------|----------|-------------|
| QA-ANLYS-001 | FR-A001 | Stock `000001` has sufficient historical data (>60 days) | 1. `GET /stock/000001/indicators` | Response has `values` dict containing keys for MA, MACD, RSI, KDJ, Bollinger indicators. Values are numbers or null. HTTP 200. | P0 | Yes |
| QA-ANLYS-002 | FR-A001 | Stock `000001` has historical data | 1. `GET /stock/000001/indicators/full` | Response is a JSON array. Each record has `date`, `open`, `high`, `low`, `close`, `volume`, `indicators` (dict with computed indicator values). Array length > 0. | P0 | Yes |
| QA-ANLYS-003 | FR-A002 | Stock `000001` has historical data | 1. `GET /stock/000001/patterns` | Response is a JSON array (may be empty). Each item has `name` (string) and `value` (integer, positive=bullish, negative=bearish). No 500 error. | P0 | Yes |
| QA-ANLYS-004 | FR-A003 | Stock `000001` has sufficient price history | 1. `GET /stock/000001/support-resistance` | Response is a JSON array. Each item has `level` (price float), `type` ("support" or "resistance"), and optionally `strength`. | P1 | Yes |
| QA-ANLYS-005 | FR-BI001 | Stock `000001` has >200 days of data | 1. `GET /stock/000001/indicators/bayesian` | Response has `symbol`, `name`, `analysis_date`, `lookback_days`, `forward_days`. Contains Bayesian probability data for RSI, MACD, KDJ bins. HTTP 200. | P0 | Yes |
| QA-ANLYS-006 | FR-A004 | Backend running | 1. `GET /indicators/explanations` 2. `GET /indicators/explanations?indicator=RSI` | Step 1: Returns dict with all indicator keys (MA, MACD, RSI, KDJ, BOLL, VOL). Step 2: Returns dict with only `RSI` key. Chinese text explanations present. | P1 | Yes |

---

## 3. Prediction (QA-PRED)

| ID | PRD Ref | Preconditions | Steps | Expected Result | Priority | Automatable |
|----|---------|---------------|-------|-----------------|----------|-------------|
| QA-PRED-001 | FR-P002 | Anthropic/Gemini API key configured, stock 000001 has data | 1. `POST /predict/000001` (empty body) | Response has `symbol`, `trend` (bullish/bearish/neutral), `confidence` (0-1 float), `signal`, `reasoning`. HTTP 200. Response time < 30s. | P0 | Yes |
| QA-PRED-002 | FR-EP001 | API key configured, stock 000001 has data | 1. `POST /predict/000001/enhanced` with body `{"sources": ["indicators", "fund_flow"], "include_bayesian": true}` | Response has enhanced fields including data source tags, Bayesian analysis. `sources_used` array matches request. | P0 | Yes |
| QA-PRED-003 | FR-EP001 | API key configured, 2+ stocks have data | 1. `POST /predict/compare` with body `{"symbols": ["000001", "600519"], "sources": ["indicators"]}` | Response has per-stock analyses and a ranking. Both symbols present in results. | P0 | Yes |
| QA-PRED-004 | FR-EP003 | Stock 000001 has data, API key configured | 1. `GET /stock/000001/ai-analysis` | Response has `symbol`, `signal`, `summary`, `points` (array), `risks` (array). On error: returns `status: "error"` with `message` instead of HTTP 500. | P0 | Yes |
| QA-PRED-005 | FR-EP003 | Stock 000001, API key | 1. `GET /stock/000001/quick-insight` | Response has `symbol`, `signal`, `confidence`, `summary`, `risk_badge`. Summary is Chinese text. Response time < 10s. | P0 | Yes |
| QA-PRED-006 | FR-PI001 | Stock 000001, API key | 1. `POST /stock/000001/move-analysis` with body `{"cost_price": 15.0, "shares": 1000}` | Response has move attribution factors. Includes market, sector, news, and technical factor weights. `symbol` is `000001`. | P1 | Yes |
| QA-PRED-007 | FR-CA001 | Stock 000001 has news/dragon tiger/pattern data | 1. `GET /stock/000001/chart-events?days=120` | Response has `symbol` and `events` array. Events have `date`, `type` (news/dragon_tiger/anomaly/pattern), `title`, `impact`. | P0 | Yes |
| QA-PRED-008 | FR-P002 | Stock 000001, API key | 1. `POST /stock/000001/analyze` (force fresh analysis) | Response is same schema as `ai-analysis` but cache is bypassed. Subsequent call to `GET /stock/000001/ai-analysis` returns the fresh result. | P1 | Yes |

---

## 4. Strategy + Backtest (QA-BT)

| ID | PRD Ref | Preconditions | Steps | Expected Result | Priority | Automatable |
|----|---------|---------------|-------|-----------------|----------|-------------|
| QA-BT-001 | FR-S001 | Backend running | 1. `GET /strategies` | Response is a JSON array with at least 3 strategy items. Each has `key`, `name`, `description`. Keys include trend_following, mean_reversion, momentum. | P0 | Yes |
| QA-BT-002 | FR-B001 | Stock 000001 has >120 days historical data | 1. `POST /backtest` with body `{"symbol": "000001", "strategy": "trend_following", "board": "main"}` | Response has `metrics` (annualized return, sharpe, max drawdown, win rate), `equity_curve`, and `report`. T+1 rule applied (no same-day sell). | P0 | Yes |
| QA-BT-003 | FR-SV002 | Stock 000001 has data | 1. `POST /backtest/v2` with body `{"symbol": "000001", "strategy": "trend_following", "board": "main", "param_overrides": {}}` | Response includes `signals`, `round_trips`, dates, attribution data, and strategy metadata in addition to v1 fields. | P0 | Yes |
| QA-BT-004 | FR-AI003 | API key configured, valid backtest has been run | 1. `POST /backtest/ai-interpret` with body `{"symbol": "000001", "strategy_name": "trend_following", "metrics": {"annual_return": "15%", "sharpe": "1.2"}, "trades_count": 10, "initial_capital": 100000, "final_capital": 115000}` | Response has `status: "success"`, `summary` (Chinese), `strategy_explain`, `strengths`, `weaknesses`, `improvement_suggestions`, `risk_analysis`, `beginner_tips`. | P0 | Yes |
| QA-BT-005 | FR-SV001 | Strategy `trend_following` exists | 1. `GET /strategies/trend_following/metadata` | Response has flow chart data and parameter metadata for the strategy. | P1 | Yes |
| QA-BT-006 | FR-AI001 | API key configured | 1. `POST /strategy-lab/nl-create` with body `{"description": "when RSI crosses above 30 buy, sell when RSI crosses above 70", "symbol": "000001"}` | Response has generated strategy configuration from natural language. Includes strategy key, parameters, and description. | P0 | Yes |
| QA-BT-007 | FR-AI002 | API key, valid strategy exists | 1. `POST /strategy-lab/ai-optimize` with body `{"symbol": "000001", "strategy_key": "trend_following", "current_params": {}, "current_metrics": {}}` | Response has optimization suggestions with recommended parameter changes and expected improvements. | P1 | Yes |
| QA-BT-008 | FR-AI003 | API key, backtest results available | 1. `POST /strategy-lab/ai-attribution` with body `{"symbol": "000001", "strategy_name": "trend_following", "round_trips": [], "metrics": {}}` | Response has attribution analysis identifying key factors in strategy performance. | P1 | Yes |
| QA-BT-009 | FR-SG001 | Paper trade signal service running, stock 000001 | 1. `GET /strategy-lab/latest-signals/000001` | Response is a JSON array. Each item has strategy name, signal direction, timestamp. May be empty if no recent signals. | P0 | Yes |
| QA-BT-010 | FR-PT002 | Paper trade service running | 1. `POST /strategy-lab/check-signals` with body `{"positions": [{"symbol": "000001", "strategy": "trend_following"}]}` | Response is a JSON array of signal items matching the provided positions. | P1 | Yes |

---

## 5. Portfolio (QA-PF)

| ID | PRD Ref | Preconditions | Steps | Expected Result | Priority | Automatable |
|----|---------|---------------|-------|-----------------|----------|-------------|
| QA-PF-001 | FR-PF001 | No existing portfolio file | 1. `GET /portfolio` | Response has `version: 1`, `updatedAt: ""`, `positions: []`. HTTP 200. | P0 | Yes |
| QA-PF-002 | FR-PF001 | Backend running | 1. `PUT /portfolio` with body `{"version": 1, "updatedAt": "2026-02-13T10:00:00", "positions": [{"symbol": "000001", "name": "Ping An", "shares": 1000, "cost_price": 15.0}]}` 2. `GET /portfolio` | Step 1: Response `status: "success"`. Step 2: Response contains the saved position with `symbol: "000001"` and `shares: 1000`. | P0 | Yes |
| QA-PF-003 | FR-PF002 | Portfolio has at least 1 position, API key configured | 1. `POST /portfolio/diagnose` with body `{"positions": [{"symbol": "000001", "name": "Ping An", "shares": 1000, "cost_price": 15.0}]}` | Response has `health_score` (0-100), `advice` (Chinese text), `risk_warnings` (array). No 500 error. Response time < 30s. | P0 | Yes |
| QA-PF-004 | FR-PF001 | Backend running | 1. `PUT /portfolio` with valid data 2. Check `data/processed/portfolio.json` exists 3. Check `data/processed/portfolio.json.bak` exists after second save | Step 2: File exists with correct JSON. Step 3: Backup file created from previous version. | P1 | No |
| QA-PF-005 | FR-PF001 | Portfolio file exists | 1. `PUT /portfolio` with `{"version": 1, "updatedAt": "2026-02-13T12:00:00", "positions": []}` 2. `GET /portfolio` | Empty positions array saved and retrieved correctly. Previous data overwritten. | P0 | Yes |
| QA-PF-006 | FR-PF002 | Empty portfolio | 1. `POST /portfolio/diagnose` with `{"positions": []}` | Response returns gracefully (not HTTP 500). May return default health score or error status. | P1 | Yes |
| QA-PF-007 | FR-PF001 | Backend running | 1. `PUT /portfolio` with invalid JSON schema (missing required fields) | Response is HTTP 422 (validation error). Error body identifies the missing fields. | P1 | Yes |
| QA-PF-008 | FR-PI003 | Portfolio and stock detail endpoints working | 1. Save portfolio with `000001` position. 2. `GET /stock/000001` | Stock detail returns valid data. Frontend can cross-reference position data with stock detail for navigation linkage. | P0 | Yes |

---

## 6. Market (QA-MKT)

| ID | PRD Ref | Preconditions | Steps | Expected Result | Priority | Automatable |
|----|---------|---------------|-------|-----------------|----------|-------------|
| QA-MKT-001 | FR-DR001 | Backend running with MarketService | 1. `GET /market/indices` | Response is a JSON array with major A-share indices (Shanghai Composite, Shenzhen Component, ChiNext). Each has `name`, `price`, `change`, `pct_change`. Never returns empty (seed values fallback). | P0 | Yes |
| QA-MKT-002 | FR-D004 | Watchlist configured | 1. `GET /market/realtime` (no symbols param) | Response returns realtime quotes for all watchlist stocks. Each record has `symbol`, `price`, `volume`. No NaN values. | P0 | Yes |
| QA-MKT-003 | FR-D005 | Dragon tiger data available (after market close) | 1. `GET /market/dragon-tiger` with valid date range 2. `GET /market/dragon-tiger/000001?days=30` | Step 1: Returns market-wide dragon tiger list. Step 2: Returns filtered records for stock 000001 only. | P1 | Yes |
| QA-MKT-004 | FR-DT001 | Dragon tiger seat data available | 1. `GET /market/dragon-tiger/000001/seats` | Response is a JSON array of seat details (broker names, buy/sell amounts). May be empty if stock has no recent dragon tiger entries. | P1 | Yes |
| QA-MKT-005 | FR-DT001 | Dragon tiger stats available | 1. `GET /market/dragon-tiger/000001/stats` | Response has `appearances_3m`, `institution_net_buy`, `avg_return_5d`, `win_rate_5d`. All are numeric. | P1 | Yes |
| QA-MKT-006 | FR-D006 | Limit up data available | 1. `GET /market/limit-up` (today) 2. `GET /market/limit-up?date=20260212` | Both return JSON arrays. Historical date returns that day's limit-up stocks. No 500 errors. | P1 | Yes |
| QA-MKT-007 | FR-SR005 | Stock 000001 has fund flow data | 1. `GET /stock/000001/fund-flow` 2. `GET /stock/000001/fund-flow/intraday` 3. `GET /stock/000001/fund-flow/detail` | Step 1: Returns daily fund flow records with main/retail net inflow. Step 2: Returns today's intraday fund flow. Step 3: Returns inflow/outflow/net amounts. No NaN in responses. | P0 | Yes |
| QA-MKT-008 | FR-SR002 | Stock 000001 has data, API key configured | 1. `GET /stock/000001/sr-analysis` | Response has support/resistance levels with AI analysis commentary. Includes current price context and fund flow integration. | P1 | Yes |

---

## 7. News + Sentiment (QA-NEWS)

| ID | PRD Ref | Preconditions | Steps | Expected Result | Priority | Automatable |
|----|---------|---------------|-------|-----------------|----------|-------------|
| QA-NEWS-001 | FR-SE001 | NewsFetcher operational, stock 000001 | 1. `GET /stock/000001/news?limit=10` | Response is a JSON array with up to 10 news items. Each has `title`, `datetime`. No NaN values. | P0 | Yes |
| QA-NEWS-002 | FR-SE001 | Stock 000001 | 1. `GET /stock/000001/anomalies` | Response is a JSON array of unusual trading activities. Each has `change_type`, `datetime`. May be empty outside trading hours. | P0 | Yes |
| QA-NEWS-003 | FR-SE002 | API key configured, stock has news | 1. `GET /stock/000001/sentiment` | Response has `symbol`, `overall` (positive/negative/neutral), `positive_count`, `negative_count`, `neutral_count`, `total_count`, `score`. | P0 | Yes |
| QA-NEWS-004 | FR-RI004 | API key configured, stock 000001 | 1. `GET /stock/000001/research` | Response has `symbol`, `news` (array), `sentiment` (object or null), `fund_holdings` (array), `analyst_ratings` (array). No NaN in nested structures. | P0 | Yes |
| QA-NEWS-005 | FR-SE003 | NewsFetcher operational | 1. `GET /market/hot-rank` | Response is a JSON array of hot stocks. Each has stock identification and ranking info. Array is non-empty during market hours. | P1 | Yes |
| QA-NEWS-006 | FR-TN003 | TrendNewsAggregator and ResonanceDetector loaded | 1. `GET /sentiment/resonance?symbols=000001,600519` | Response has `events` array (may be empty), `total` count. Each event has resonance level (L1/L2/L3), platform sources, and matched stocks. | P0 | Yes |
| QA-NEWS-007 | FR-TN004 | API key configured, news sources available | 1. `GET /sentiment/report?symbols=000001,600519` | Response has 6 sections: `core_trends`, `policy_signals`, `global_linkage`, `risk_alerts`, `sector_outlook`, `overall_outlook`. On error: returns `status: "error"` with `message`. | P0 | Yes |
| QA-NEWS-008 | FR-TN005 | Sentiment service running | 1. `GET /sentiment/market-pulse?symbols=000001` | Response has `hot_events` (array), `holdings_news` (dict). Provides dashboard-ready market pulse data. | P0 | Yes |
| QA-NEWS-009 | FR-GM004 | CrossMarketAnalyzer loaded, global data available | 1. `GET /sentiment/cross-market/000001` | Response has `symbol`, `combined_impact_score` (float), `impact_direction`. Includes peer performance and correlation data. | P1 | Yes |
| QA-NEWS-010 | FR-TN001 | TrendNewsAggregator operational | 1. `GET /sentiment/resonance` (no symbols param) 2. `GET /sentiment/market-pulse` (no symbols param) | Both return valid responses without errors. Demonstrates aggregation works without watchlist context. | P1 | Yes |

---

## 8. AI Advisor (QA-ADV)

| ID | PRD Ref | Preconditions | Steps | Expected Result | Priority | Automatable |
|----|---------|---------------|-------|-----------------|----------|-------------|
| QA-ADV-001 | FR-TA001 | API key configured, stock 000001 has data | 1. `GET /advisor/stock/000001` | Response has `symbol`, `action` (buy/add/hold/reduce/sell/watch), `action_label` (Chinese), `confidence` (0-1), `risk_level`, `quant_signals`, `ai_reasoning` (array), `risk_warnings`, `disclaimer`. | P0 | Yes |
| QA-ADV-002 | FR-TA002 | API key configured, 2+ stocks | 1. `GET /advisor/watchlist?symbols=000001,600519` | Response has `items` array with advice per stock, `total` count. Each item has action and confidence. `disclaimer` present. | P0 | Yes |
| QA-ADV-003 | FR-TA003 | API key configured | 1. `POST /advisor/portfolio` with body `{"positions": [{"symbol": "000001", "shares": 1000, "cost_price": 15.0}]}` | Response has `positions` array with add/reduce/stop-loss advice per position. `total` count matches input. `disclaimer` present. | P0 | Yes |
| QA-ADV-004 | FR-HS003 | Trading calendar loaded, stock 000001 | 1. `GET /advisor/holiday-impact/000001` | Response has `symbol`, `impact_score` (0-1 float), `impact_direction`, `factors` (array), `ai_assessment`, `suggested_action`, `confidence`, `disclaimer`. | P1 | Yes |
| QA-ADV-005 | FR-HS004 | API key configured, global market data available | 1. `GET /advisor/reopen-briefing` | Response has `market_outlook`, `confidence`, `summary` (Chinese), `key_events`, `position_impacts`, `recommendations`, `risk_warnings`, `disclaimer`. | P1 | Yes |
| QA-ADV-006 | FR-TA001 | API key missing or invalid | 1. Remove API key from environment. 2. `GET /advisor/stock/000001` | Response has `status: "error"`, `action: "watch"`, `confidence: 0.0`, `risk_warnings` includes error message. No HTTP 500. Graceful degradation. | P0 | Yes |

---

## 9. Holiday Sentinel (QA-HS)

| ID | PRD Ref | Preconditions | Steps | Expected Result | Priority | Automatable |
|----|---------|---------------|-------|-----------------|----------|-------------|
| QA-HS-001 | FR-HS001 | TradingCalendar loaded, `config/calendar.yaml` exists | 1. `GET /market/calendar` | Response has `is_trading_day` (bool), `current_session` (pre_market/morning/lunch_break/afternoon/after_hours/closed), `next_trading_day` (date string), `is_holiday_period` (bool). | P0 | Yes |
| QA-HS-002 | FR-HS001 | Calendar loaded | 1. Check response from `GET /market/calendar` on a known Saturday | `is_trading_day` is `false`. `next_trading_day` is the following Monday (or later if Monday is a holiday). | P0 | No |
| QA-HS-003 | FR-HS001 | Calendar loaded | 1. Check `current_session` value during different time windows (before 9:15, 9:30-11:30, 11:30-13:00, 13:00-15:00, after 15:00) | Session value matches the correct market session for the current time. | P1 | No |
| QA-HS-004 | FR-HS001 | Calendar loaded, known public holiday configured | 1. `GET /market/calendar` on a known Chinese public holiday (e.g., Spring Festival) | `is_trading_day` is `false`. `is_holiday_period` is `true`. `next_trading_day` points to the first post-holiday trading day. | P1 | No |
| QA-HS-005 | FR-HS001 | Manual override configured in `config/calendar.yaml` | 1. Add a manual override marking a specific date as non-trading. 2. `GET /market/calendar` on that date. | `is_trading_day` reflects the manual override, not the default calendar. | P2 | No |
| QA-HS-006 | FR-HS001 | Scheduler calendar endpoint available | 1. `GET /scheduler/calendar?days=30` | Response has `days` (array of 30 items), `today`, `next_trading_day`. Each day has `date`, `is_trading_day`, `is_weekend`, `is_holiday`, `day_of_week`. Weekend days have `is_weekend: true`. | P0 | Yes |

---

## 10. Global Market (QA-GM)

| ID | PRD Ref | Preconditions | Steps | Expected Result | Priority | Automatable |
|----|---------|---------------|-------|-----------------|----------|-------------|
| QA-GM-001 | FR-GM001 | GlobalMarketFetcher loaded, `config/global_market.yaml` exists | 1. `GET /global-market/snapshot` | Response has `indices` (array), `commodities` (array), `currencies` (array). On fetch failure: returns empty arrays, not HTTP 500. | P0 | Yes |
| QA-GM-002 | FR-GM001 | Global market data available (yfinance) | 1. `GET /global-market/indices` | Response is a JSON array. Each item has name, region, price, change data. Includes US (S&P 500, Nasdaq), HK (Hang Seng), and other major indices. | P0 | Yes |
| QA-GM-003 | FR-GM001 | Global market data available | 1. `GET /global-market/commodities` | Response is a JSON array with commodity items (gold, oil, etc.). Each has name, price, change. | P1 | Yes |
| QA-GM-004 | FR-GM001 | Global market data available | 1. `GET /global-market/currencies` | Response is a JSON array with currency exchange rates (USD/CNY, EUR/CNY, etc.). Each has name, price, change. | P1 | Yes |
| QA-GM-005 | FR-GM004 | CrossMarketAnalyzer loaded, global data available | 1. `GET /sentiment/cross-market/600519` (Moutai, consumer sector) | Response has `symbol`, `combined_impact_score`, `impact_direction`. Includes peer analysis from US/HK markets and commodity correlations relevant to the stock's sector. | P1 | Yes |

---

## 11. Scheduler (QA-SCHED)

| ID | PRD Ref | Preconditions | Steps | Expected Result | Priority | Automatable |
|----|---------|---------------|-------|-----------------|----------|-------------|
| QA-SCHED-001 | FR-SS001 | TimelineScheduler loaded | 1. `GET /scheduler/status` | Response has current profile (trading_day/holiday/pre_market/after_hours), mode information, and next switch time. | P0 | Yes |
| QA-SCHED-002 | FR-SS004 | Scheduler loaded | 1. `GET /scheduler/plans` | Response has `plans` array with 4 entries (trading_day, holiday, pre_market, after_hours). Each plan has `name`, `label` (Chinese), `tasks` array. Each task has `name`, `enabled` (bool), `description`. | P0 | Yes |
| QA-SCHED-003 | FR-SS004 | Scheduler loaded | 1. `PUT /scheduler/plans/trading_day` with body `{"tasks": {"task_sentiment_scan": false}}` 2. `GET /scheduler/plans` | Step 1: Response `status: "success"`. Step 2: The `trading_day` plan shows `task_sentiment_scan` as `enabled: false`. | P1 | Yes |
| QA-SCHED-004 | FR-SS004 | Scheduler loaded | 1. `POST /scheduler/override` with body `{"profile": "holiday"}` 2. `GET /scheduler/status` 3. `POST /scheduler/override` with body `{"profile": null}` 4. `GET /scheduler/status` | Step 1-2: Status shows override active with `holiday` profile. Step 3-4: Override cleared, status shows auto-detected profile. | P0 | Yes |
| QA-SCHED-005 | FR-SS004 | Scheduler loaded | 1. `POST /scheduler/override` with body `{"profile": "invalid_value"}` | HTTP 400 with error message listing valid profiles. | P1 | Yes |
| QA-SCHED-006 | FR-HS005 | SentinelConfigService loaded, `config/sentinel.yaml` exists | 1. `GET /scheduler/sentinel-config` 2. `PUT /scheduler/sentinel-config` with updated config body 3. `GET /scheduler/sentinel-config` | Step 1: Returns current sentinel config with data sources and notification channels. Step 2: Returns `status: "success"`. Step 3: Reflects the updated config values. | P1 | Yes |

---

## 12. Settings + Admin (QA-ADMIN)

| ID | PRD Ref | Preconditions | Steps | Expected Result | Priority | Automatable |
|----|---------|---------------|-------|-----------------|----------|-------------|
| QA-ADMIN-001 | FR-ST001 | Config files exist | 1. `GET /settings/config/stocks` 2. `GET /settings/config/analysis` | Both return `{"section": "...", "config": {...}}`. Config contains expected YAML-derived structure. HTTP 200. | P0 | Yes |
| QA-ADMIN-002 | FR-W001 | Watchlist has stocks | 1. `POST /settings/watchlist/add` with `{"symbol": "300750", "name": "CATL", "board": "gem"}` 2. `GET /watchlist` 3. `DELETE /settings/watchlist/300750` 4. `GET /watchlist` | Step 2: Watchlist includes 300750. Step 3: Response `status: "success"`. Step 4: Watchlist no longer includes 300750. | P0 | Yes |
| QA-ADMIN-003 | FR-ST001 | AdminService loaded | 1. `GET /admin/keys` 2. `POST /admin/keys` with `{"provider": "test", "key": "sk-test-123", "label": "test-key"}` 3. `GET /admin/keys` 4. `DELETE /admin/keys/test/test-key` | Step 1: Returns array of existing keys (masked). Step 3: New key appears in list with masked value. Step 4: Key removed, `status: "success"`. | P0 | Yes |
| QA-ADMIN-004 | FR-ST002 | AdminService loaded | 1. `GET /admin/usage` | Response has usage dashboard data for last 7 days. Contains request counts and token usage. HTTP 200. | P1 | Yes |
| QA-ADMIN-005 | FR-PM001 | PromptManager loaded | 1. `GET /prompts` 2. `POST /prompts` with `{"name": "Test Prompt", "category": "custom", "user_template": "Analyze {symbol}"}` 3. `GET /prompts/{id}` (using returned id) 4. `PUT /prompts/{id}` with `{"name": "Updated Test"}` 5. `DELETE /prompts/{id}` | Full CRUD cycle works. Step 3: Returns prompt with version history. Step 4: Version incremented. Step 5: Returns `status: "deleted"`. | P0 | Yes |
| QA-ADMIN-006 | FR-PM003 | PromptManager and PromptTester loaded, API key configured, test prompt exists | 1. `POST /prompts/{id}/test` with `{"variables": {"symbol": "000001"}}` 2. `POST /prompts/{id}/optimize` with `{"test_output": "sample output text"}` | Step 1: Returns test execution result with LLM output. Step 2: Returns optimization suggestions for the prompt. | P1 | Yes |

---

## 13. UX Interaction (QA-UX)

| ID | PRD Ref | Preconditions | Steps | Expected Result | Priority | Automatable |
|----|---------|---------------|-------|-----------------|----------|-------------|
| QA-UX-001 | FR-UX001 | Frontend running, watchlist has stock 000001, portfolio is empty | 1. Open Dashboard in browser. 2. In watchlist table, click "..." menu on stock 000001 row. 3. Click "Add Position". 4. Fill cost price (15.0) and shares (1000). 5. Submit. 6. Navigate to Portfolio page. | Step 2: Dropdown menu appears with "View Detail", "Add Position", "Remove". Step 5: Toast shows "Position added". Step 6: Portfolio shows 000001 position. Stock is auto-added to watchlist if not present. | P0 | No |
| QA-UX-002 | FR-UX002 | Frontend running, portfolio has stock 000001 position | 1. Navigate to Portfolio page. 2. Click "..." menu on 000001 row. 3. Click "Delete Position". 4. Observe confirmation dialog. 5. Click "Cancel". 6. Repeat step 3. 7. Click "Delete" (red button). | Step 4: Confirmation dialog appears with destructive styling. Step 5: Dialog closes, position unchanged. Step 7: Position removed, toast shows "Position deleted". | P0 | No |
| QA-UX-003 | FR-UX003 | Frontend running, watchlist has stocks | 1. On Dashboard watchlist table, verify each row has a "..." dropdown menu button. 2. Click it and verify menu items: "View Detail", "Add Position", "Remove". 3. On Portfolio table, verify "Edit", "Delete", "View Detail" options. | All data tables have row-level action menus. Destructive actions (Remove, Delete) shown in red text. Menu closes after action click. | P0 | No |
| QA-UX-004 | FR-UX004 | Frontend running, watchlist configured | 1. Open Dashboard. 2. Use stock search to add a new stock to watchlist. 3. Observe the watchlist table. 4. Disconnect network. 5. Try adding another stock. 6. Reconnect network. | Step 2: Stock appears in watchlist immediately (optimistic update). Step 3: Toast shows success. Step 5: UI updates optimistically, then rolls back with error toast when request fails. Step 6: UI is consistent after reconnection. | P0 | No |

---

## 14. Notifications (QA-NOTIF)

| ID | PRD Ref | Preconditions | Steps | Expected Result | Priority | Automatable |
|----|---------|---------------|-------|-----------------|----------|-------------|
| QA-NOTIF-001 | FR-NP003 | Redis running, at least 1 notification in Redis list | 1. `POST /notifications/trigger-test` 2. `GET /notifications/recent?limit=10` | Step 1: Returns `status: "ok"` with test notification object containing `id`, `type`, `title`, `message`, `severity`, `timestamp`. Step 2: Array includes the test notification. Each item has `read` field (bool). | P0 | Yes |
| QA-NOTIF-002 | FR-NP003 | Redis running, unread notification exists | 1. `POST /notifications/trigger-test` (get the returned `id`) 2. `POST /notifications/read` with body `["<notification-id>"]` 3. `GET /notifications/recent` | Step 2: Returns `status: "ok"`, `marked: 1`. Step 3: The notification with the given ID has `read: true`. | P0 | Yes |
| QA-NOTIF-003 | FR-NP003 | Redis running, multiple unread notifications exist | 1. Trigger 3 test notifications. 2. `POST /notifications/read-all` 3. `GET /notifications/recent` 4. `GET /notifications/unread-count` | Step 2: Returns `status: "ok"` with `marked` count >= 3. Step 3: All notifications have `read: true`. Step 4: Returns `count: 0`. | P0 | Yes |
| QA-NOTIF-004 | FR-NP003 | Redis is NOT running or unavailable | 1. `GET /notifications/recent` 2. `GET /notifications/unread-count` 3. `POST /notifications/read` with `["fake-id"]` | Step 1: Returns empty array `[]`. Step 2: Returns `{"count": 0}`. Step 3: Returns `status: "error"` with message. No HTTP 500 on any endpoint. | P1 | Yes |

---

## Summary by Priority

| Priority | Count | Description |
|----------|-------|-------------|
| P0 | 55 | Critical path tests -- must pass before any release |
| P1 | 31 | Important functionality -- should pass for quality release |
| P2 | 4 | Edge cases and enhancements -- nice to have |

## Summary by Automatable

| Automatable | Count | Description |
|-------------|-------|-------------|
| Yes | 80 | Can be converted to automated API tests (pytest + httpx) |
| No | 10 | Requires manual browser interaction or time-dependent conditions |
