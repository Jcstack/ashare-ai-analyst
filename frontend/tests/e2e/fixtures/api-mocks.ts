/**
 * Shared page.route() interceptors for all 18 API domains.
 *
 * Usage in spec files:
 *   import { mockAllApis } from './fixtures/api-mocks';
 *   test.beforeEach(async ({ page }) => { await mockAllApis(page); });
 */

import { Page } from '@playwright/test';
import {
  MOCK_ADMIN_KEYS,
  MOCK_ADVISOR,
  MOCK_AI_ANALYSIS,
  MOCK_BACKTEST_RESULT,
  MOCK_CALENDAR,
  MOCK_DRAGON_TIGER,
  MOCK_GLOBAL_MARKET,
  MOCK_INDICATORS,
  MOCK_LIMIT_UP,
  MOCK_MARKET_INDICES,
  MOCK_NOTIFICATIONS,
  MOCK_OHLCV,
  MOCK_PORTFOLIO,
  MOCK_PREDICTION,
  MOCK_PROMPTS,
  MOCK_REALTIME_QUOTES,
  MOCK_SCHEDULER,
  MOCK_SEARCH_RESULTS,
  MOCK_SENTIMENT,
  MOCK_SETTINGS_CONFIG,
  MOCK_STOCK_DETAIL,
  MOCK_STRATEGIES,
  MOCK_USAGE,
  MOCK_WATCHLIST,
} from './mock-data';

/**
 * Intercept all API calls with deterministic mock data.
 * Call this in beforeEach to ensure all network requests are mocked.
 */
export async function mockAllApis(page: Page) {
  // --- Stocks ---
  await page.route('**/api/v1/watchlist', (route) =>
    route.fulfill({ json: MOCK_WATCHLIST }),
  );
  await page.route('**/api/v1/stock/*/ohlcv*', (route) =>
    route.fulfill({ json: MOCK_OHLCV }),
  );
  await page.route('**/api/v1/stock/*/indicators/full', (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route('**/api/v1/stock/*/indicators/bayesian', (route) =>
    route.fulfill({ json: { symbol: '000001', indicators: [] } }),
  );
  await page.route('**/api/v1/stock/*/indicators', (route) =>
    route.fulfill({ json: MOCK_INDICATORS }),
  );
  await page.route('**/api/v1/stock/*/patterns', (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route('**/api/v1/stock/*/support-resistance', (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route('**/api/v1/stock/*/fund-flow/detail', (route) =>
    route.fulfill({ json: { symbol: '000001' } }),
  );
  await page.route('**/api/v1/stock/*/fund-flow/intraday', (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route('**/api/v1/stock/*/fund-flow', (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route('**/api/v1/stock/*/intraday-trades', (route) =>
    route.fulfill({
      json: {
        buy_volume: 800000, sell_volume: 600000,
        neutral_volume: 100000, total_volume: 1500000,
        buy_ratio: 0.53, sell_ratio: 0.40,
      },
    }),
  );
  await page.route('**/api/v1/stock/*/realtime-snapshot', (route) =>
    route.fulfill({
      json: { symbol: '000001', quote: null, trades: null, fund_flow: null },
    }),
  );
  await page.route('**/api/v1/stock/*/comprehensive-analysis', (route) =>
    route.fulfill({ json: MOCK_AI_ANALYSIS }),
  );
  await page.route('**/api/v1/stock/*/sr-analysis', (route) =>
    route.fulfill({ json: { symbol: '000001', levels: [], analysis: '' } }),
  );
  // Stock detail (must come after more specific /stock/* routes)
  await page.route('**/api/v1/stock/*', (route) => {
    const url = route.request().url();
    // Only match /stock/{symbol} not /stock/{symbol}/xxx
    const parts = url.split('/api/v1/stock/')[1]?.split('/');
    if (parts && parts.length === 1) {
      return route.fulfill({ json: MOCK_STOCK_DETAIL });
    }
    return route.continue();
  });

  // --- Search ---
  await page.route('**/api/v1/stocks/search*', (route) =>
    route.fulfill({ json: MOCK_SEARCH_RESULTS }),
  );

  // --- Market ---
  await page.route('**/api/v1/market/indices', (route) =>
    route.fulfill({ json: MOCK_MARKET_INDICES }),
  );
  await page.route('**/api/v1/market/realtime*', (route) =>
    route.fulfill({ json: MOCK_REALTIME_QUOTES }),
  );
  await page.route('**/api/v1/market/dragon-tiger*', (route) =>
    route.fulfill({ json: MOCK_DRAGON_TIGER }),
  );
  await page.route('**/api/v1/market/limit-up*', (route) =>
    route.fulfill({ json: MOCK_LIMIT_UP }),
  );
  await page.route('**/api/v1/market/calendar', (route) =>
    route.fulfill({ json: MOCK_CALENDAR }),
  );
  await page.route('**/api/v1/market/hot-rank*', (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route('**/api/v1/market/ai-overview', (route) =>
    route.fulfill({ json: { status: 'success', summary: '市场偏强' } }),
  );

  // --- Predictions ---
  await page.route('**/api/v1/predict/compare', (route) =>
    route.fulfill({ json: { stocks: [MOCK_PREDICTION], summary: '整体看多' } }),
  );
  await page.route('**/api/v1/predict/*/enhanced', (route) =>
    route.fulfill({ json: MOCK_PREDICTION }),
  );
  await page.route('**/api/v1/predict/*', (route) =>
    route.fulfill({ json: MOCK_PREDICTION }),
  );

  // --- Portfolio ---
  await page.route('**/api/v1/portfolio/diagnose', (route) =>
    route.fulfill({ json: { overall: '持仓健康', suggestions: [] } }),
  );
  await page.route('**/api/v1/portfolio', (route) =>
    route.fulfill({ json: MOCK_PORTFOLIO }),
  );

  // --- Backtest ---
  await page.route('**/api/v1/strategies/*/metadata', (route) =>
    route.fulfill({ json: MOCK_STRATEGIES[0] }),
  );
  await page.route('**/api/v1/strategies', (route) =>
    route.fulfill({ json: MOCK_STRATEGIES }),
  );
  await page.route('**/api/v1/backtest/ai-interpret', (route) =>
    route.fulfill({ json: { analysis: '策略表现良好' } }),
  );
  await page.route('**/api/v1/backtest/v2', (route) =>
    route.fulfill({ json: MOCK_BACKTEST_RESULT }),
  );
  await page.route('**/api/v1/backtest', (route) =>
    route.fulfill({ json: MOCK_BACKTEST_RESULT }),
  );

  // --- News ---
  await page.route('**/api/v1/stock/*/news', (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route('**/api/v1/stock/*/anomalies', (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route('**/api/v1/stock/*/sentiment', (route) =>
    route.fulfill({ json: { sentiment: 'neutral', score: 0.5 } }),
  );
  await page.route('**/api/v1/stock/*/research', (route) =>
    route.fulfill({ json: [] }),
  );

  // --- Agent / AI ---
  await page.route('**/api/v1/stock/*/ai-analysis', (route) =>
    route.fulfill({ json: MOCK_AI_ANALYSIS }),
  );
  await page.route('**/api/v1/stock/*/quick-insight', (route) =>
    route.fulfill({
      json: { symbol: '000001', signal: 'bullish', summary: '偏强' },
    }),
  );
  await page.route('**/api/v1/stock/*/analyze', (route) =>
    route.fulfill({ json: MOCK_AI_ANALYSIS }),
  );
  await page.route('**/api/v1/stock/*/alerts', (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route('**/api/v1/stock/*/move-analysis', (route) =>
    route.fulfill({ json: { analysis: '涨跌归因' } }),
  );
  await page.route('**/api/v1/stock/*/dragon-tiger/ai-analysis', (route) =>
    route.fulfill({ json: { analysis: '机构动向' } }),
  );
  await page.route('**/api/v1/stock/*/chart-events', (route) =>
    route.fulfill({ json: [] }),
  );

  // --- Notifications ---
  await page.route('**/api/v1/notifications/recent', (route) =>
    route.fulfill({ json: MOCK_NOTIFICATIONS }),
  );
  await page.route('**/api/v1/notifications/unread-count', (route) =>
    route.fulfill({ json: { count: 1 } }),
  );
  await page.route('**/api/v1/notifications/read*', (route) =>
    route.fulfill({ json: { success: true } }),
  );

  // --- Admin ---
  await page.route('**/api/v1/admin/keys', (route) =>
    route.fulfill({ json: MOCK_ADMIN_KEYS }),
  );
  await page.route('**/api/v1/admin/usage', (route) =>
    route.fulfill({ json: MOCK_USAGE }),
  );
  await page.route('**/api/v1/admin/balance', (route) =>
    route.fulfill({ json: { available: true } }),
  );
  await page.route('**/api/v1/admin/routing', (route) =>
    route.fulfill({ json: { strategy: 'hybrid' } }),
  );
  await page.route('**/api/v1/admin/schedule-status', (route) =>
    route.fulfill({ json: MOCK_SCHEDULER.status }),
  );

  // --- Settings ---
  await page.route('**/api/v1/settings/config/*', (route) =>
    route.fulfill({ json: MOCK_SETTINGS_CONFIG }),
  );
  await page.route('**/api/v1/settings/watchlist*', (route) =>
    route.fulfill({ json: { success: true } }),
  );

  // --- Strategy Lab ---
  await page.route('**/api/v1/strategy-lab/nl-create', (route) =>
    route.fulfill({ json: { strategy_key: 'custom', name: '自定义' } }),
  );
  await page.route('**/api/v1/strategy-lab/ai-optimize', (route) =>
    route.fulfill({ json: { optimized_params: {} } }),
  );
  await page.route('**/api/v1/strategy-lab/ai-attribution', (route) =>
    route.fulfill({ json: { analysis: '归因分析' } }),
  );
  await page.route('**/api/v1/strategy-lab/latest-signals/*', (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route('**/api/v1/strategy-lab/check-signals', (route) =>
    route.fulfill({ json: { signals: [] } }),
  );

  // --- Prompts ---
  await page.route('**/api/v1/prompts/*/test', (route) =>
    route.fulfill({ json: { result: 'Test output' } }),
  );
  await page.route('**/api/v1/prompts/*/optimize', (route) =>
    route.fulfill({ json: { optimized: 'Improved prompt' } }),
  );
  await page.route('**/api/v1/prompts/*', (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: MOCK_PROMPTS[0] });
    }
    return route.fulfill({ json: { success: true } });
  });
  await page.route('**/api/v1/prompts', (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: MOCK_PROMPTS });
    }
    return route.fulfill({ json: { id: 'p3', name: 'New' } });
  });

  // --- Global Market ---
  await page.route('**/api/v1/global-market/snapshot', (route) =>
    route.fulfill({ json: MOCK_GLOBAL_MARKET }),
  );
  await page.route('**/api/v1/global-market/indices', (route) =>
    route.fulfill({ json: MOCK_GLOBAL_MARKET.indices }),
  );
  await page.route('**/api/v1/global-market/commodities', (route) =>
    route.fulfill({ json: MOCK_GLOBAL_MARKET.commodities }),
  );
  await page.route('**/api/v1/global-market/currencies', (route) =>
    route.fulfill({ json: MOCK_GLOBAL_MARKET.currencies }),
  );

  // --- Advisor ---
  await page.route('**/api/v1/advisor/stock/*', (route) =>
    route.fulfill({ json: MOCK_ADVISOR }),
  );
  await page.route('**/api/v1/advisor/watchlist', (route) =>
    route.fulfill({ json: { strategies: [] } }),
  );
  await page.route('**/api/v1/advisor/portfolio', (route) =>
    route.fulfill({ json: { overall: '合理', suggestions: [] } }),
  );
  await page.route('**/api/v1/advisor/holiday-impact/*', (route) =>
    route.fulfill({ json: { impact_score: 3, factors: [] } }),
  );
  await page.route('**/api/v1/advisor/reopen-briefing', (route) =>
    route.fulfill({ json: { summary: '节后展望' } }),
  );

  // --- Sentiment ---
  await page.route('**/api/v1/sentiment/resonance', (route) =>
    route.fulfill({ json: MOCK_SENTIMENT.resonance }),
  );
  await page.route('**/api/v1/sentiment/report', (route) =>
    route.fulfill({ json: MOCK_SENTIMENT.report }),
  );
  await page.route('**/api/v1/sentiment/market-pulse', (route) =>
    route.fulfill({ json: MOCK_SENTIMENT.market_pulse }),
  );
  await page.route('**/api/v1/sentiment/cross-market/*', (route) =>
    route.fulfill({ json: { symbol: '000001', impact: 0.3 } }),
  );

  // --- Scheduler ---
  await page.route('**/api/v1/scheduler/status', (route) =>
    route.fulfill({ json: MOCK_SCHEDULER.status }),
  );
  await page.route('**/api/v1/scheduler/plans*', (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: MOCK_SCHEDULER.plans });
    }
    return route.fulfill({ json: { success: true } });
  });
  await page.route('**/api/v1/scheduler/override', (route) =>
    route.fulfill({ json: { success: true } }),
  );
  await page.route('**/api/v1/scheduler/calendar', (route) =>
    route.fulfill({ json: MOCK_SCHEDULER.calendar }),
  );
  await page.route('**/api/v1/scheduler/sentinel-config', (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: { data_sources: {}, channels: {} } });
    }
    return route.fulfill({ json: { success: true } });
  });

  // --- Indicator Explanations ---
  await page.route('**/api/v1/indicators/explanations*', (route) =>
    route.fulfill({
      json: {
        MA: { name: '移动平均线', description: '趋势指标' },
        RSI: { name: '相对强弱指标', description: '超买超卖' },
      },
    }),
  );
}
