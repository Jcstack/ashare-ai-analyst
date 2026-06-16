/**
 * Mock response payloads for all API domains.
 * Used by api-mocks.ts to provide deterministic test data.
 */

export const MOCK_WATCHLIST = [
  {
    symbol: '000001',
    name: '平安银行',
    board: 'main',
    close: 10.5,
    open: 10.2,
    high: 10.8,
    low: 10.1,
    change: 0.3,
    pct_change: 2.94,
    volume: 1500000,
  },
  {
    symbol: '600519',
    name: '贵州茅台',
    board: 'main',
    close: 1800.0,
    open: 1790.0,
    high: 1810.0,
    low: 1785.0,
    change: 10.0,
    pct_change: 0.56,
    volume: 50000,
  },
];

export const MOCK_STOCK_DETAIL = {
  symbol: '000001',
  name: '平安银行',
  board: 'main',
  close: 10.5,
  open: 10.2,
  high: 10.8,
  low: 10.1,
  change: 0.3,
  pct_change: 2.94,
  volume: 1500000,
};

export const MOCK_OHLCV = Array.from({ length: 30 }, (_, i) => ({
  date: `2024-01-${String(i + 1).padStart(2, '0')}`,
  open: 10.0 + Math.random(),
  high: 10.5 + Math.random(),
  low: 9.5 + Math.random(),
  close: 10.2 + Math.random() * 0.5,
  volume: 1000000 + Math.floor(Math.random() * 500000),
}));

export const MOCK_INDICATORS = {
  values: {
    RSI_14: 55.0,
    MACD: 0.05,
    MACD_signal: 0.03,
    MACD_hist: 0.02,
    KDJ_K: 65.0,
    KDJ_D: 60.0,
    KDJ_J: 75.0,
  },
};

export const MOCK_REALTIME_QUOTES = [
  {
    symbol: '000001',
    name: '平安银行',
    price: 10.5,
    change: 0.3,
    pct_change: 2.94,
    volume: 1500000,
  },
  {
    symbol: '600519',
    name: '贵州茅台',
    price: 1800.0,
    change: 10.0,
    pct_change: 0.56,
    volume: 50000,
  },
];

export const MOCK_MARKET_INDICES = [
  { symbol: '000001', name: '上证指数', price: 3100.0, change: 15.0, pct_change: 0.49 },
  { symbol: '399001', name: '深证成指', price: 10200.0, change: 50.0, pct_change: 0.49 },
];

export const MOCK_DRAGON_TIGER = [
  {
    symbol: '000001',
    name: '平安银行',
    date: '2024-01-15',
    reason: '日涨幅偏离值达7%',
    buy_amount: 5000000,
    sell_amount: 3000000,
  },
];

export const MOCK_LIMIT_UP = [
  {
    symbol: '300001',
    name: '特锐德',
    price: 25.0,
    pct_change: 20.0,
    first_limit_time: '09:31:00',
    reason: '新能源概念',
  },
];

export const MOCK_PREDICTION = {
  symbol: '000001',
  trend: 'bullish',
  signal: 'buy',
  confidence: 0.75,
  risk_level: 'medium',
  reasoning: ['趋势向好', '均线金叉'],
  key_factors: ['MACD转正', '成交量放大'],
  risk_warnings: ['大盘调整风险'],
  target_price_range: { low: 10.5, high: 11.8 },
};

export const MOCK_PORTFOLIO = {
  positions: [
    {
      symbol: '000001',
      name: '平安银行',
      shares: 1000,
      cost: 10.0,
      current_price: 10.5,
      pnl: 500,
      pnl_pct: 5.0,
    },
  ],
  summary: {
    total_value: 10500,
    total_cost: 10000,
    total_pnl: 500,
    total_pnl_pct: 5.0,
  },
};

export const MOCK_BACKTEST_RESULT = {
  success: true,
  strategy: 'ma_cross',
  metrics: {
    total_return: 0.15,
    annual_return: 0.18,
    sharpe: 1.2,
    max_drawdown: -0.08,
    win_rate: 0.55,
    profit_factor: 1.5,
  },
  trades: [
    { date: '2024-01-15', action: 'buy', price: 10.0, shares: 100 },
    { date: '2024-02-15', action: 'sell', price: 11.5, shares: 100 },
  ],
};

export const MOCK_STRATEGIES = [
  { key: 'ma_cross', name: '均线交叉', description: '双均线交叉策略' },
  { key: 'rsi_reversal', name: 'RSI反转', description: 'RSI超买超卖反转策略' },
  { key: 'momentum', name: '动量策略', description: '基于价格动量的趋势追踪' },
];

export const MOCK_GLOBAL_MARKET = {
  indices: [
    { symbol: '^GSPC', name: 'S&P500', region: 'US', price: 4500.0, change: 20.0, pct_change: 0.45 },
    { symbol: '^HSI', name: '恒生指数', region: 'HK', price: 17000.0, change: -100.0, pct_change: -0.59 },
  ],
  commodities: [
    { symbol: 'GC=F', name: 'Gold', unit: 'USD/oz', price: 2050.0, change: 10.0, pct_change: 0.49 },
  ],
  currencies: [
    { symbol: 'CNY=X', name: 'USD/CNY', price: 7.25, change: 0.01, pct_change: 0.14 },
  ],
};

export const MOCK_SEARCH_RESULTS = [
  { symbol: '000001', name: '平安银行', board: 'main' },
  { symbol: '000002', name: '万科A', board: 'main' },
];

export const MOCK_NOTIFICATIONS = [
  {
    id: 'n1',
    type: 'alert',
    title: '成交量异常',
    message: '平安银行成交量较昨日放大200%',
    read: false,
    time: '2024-01-15T10:00:00',
  },
];

export const MOCK_AI_ANALYSIS = {
  status: 'success',
  symbol: '000001',
  signal: 'bullish',
  summary: '短期看多，资金持续流入',
  points: ['均线多头排列', '资金净流入', 'MACD金叉'],
  risks: ['大盘系统性风险'],
};

export const MOCK_CALENDAR = {
  date: '2026-02-13',
  is_trading_day: true,
  current_session: 'afternoon',
  next_trading_day: '2026-02-16',
  is_holiday_period: false,
};

export const MOCK_ADVISOR = {
  symbol: '000001',
  action: 'hold',
  confidence: 0.65,
  layer1_signals: { trend: 'neutral', momentum: 'positive' },
  layer2_analysis: { summary: '建议持有观望，等待突破确认' },
};

export const MOCK_SENTIMENT = {
  resonance: [
    { title: '银行板块热点', level: 'L2', sources: ['东方财富', '新浪'], sentiment: 'positive' },
  ],
  report: { summary: '市场情绪偏多，科技板块领涨' },
  market_pulse: { sentiment: 'positive', score: 0.7 },
};

export const MOCK_SCHEDULER = {
  status: { mode: 'normal', active_profile: 'trading_day' },
  plans: [
    { name: 'daily_analysis', enabled: true, schedule: '15:30' },
    { name: 'morning_scan', enabled: true, schedule: '09:15' },
  ],
  calendar: Array.from({ length: 30 }, (_, i) => ({
    date: `2026-02-${String(i + 1).padStart(2, '0')}`,
    is_trading: i % 7 < 5,
    session: 'closed',
  })),
};

export const MOCK_PROMPTS = [
  { id: 'p1', name: 'Default Analysis', template: 'Analyze {symbol}', category: 'analysis' },
  { id: 'p2', name: 'Risk Assessment', template: 'Assess risk for {symbol}', category: 'risk' },
];

export const MOCK_ADMIN_KEYS = [
  { provider: 'anthropic', label: 'default', masked: 'sk-...abc' },
  { provider: 'openai', label: 'backup', masked: 'sk-...xyz' },
];

export const MOCK_USAGE = {
  total_requests: 100,
  total_cost: 1.5,
  by_provider: {
    anthropic: { requests: 80, cost: 1.2 },
    openai: { requests: 20, cost: 0.3 },
  },
};

export const MOCK_SETTINGS_CONFIG = {
  watchlist: [
    { symbol: '000001', name: '平安银行', board: 'main' },
    { symbol: '600519', name: '贵州茅台', board: 'main' },
  ],
};
