/** A-share convention: red = up/bullish, green = down/bearish */
export const MARKET_COLORS = {
  up: "var(--color-market-up)",
  down: "var(--color-market-down)",
  flat: "var(--color-market-flat)",
} as const

/** Signal colors for buy/sell/hold/wait */
export const SIGNAL_COLORS = {
  buy: "var(--color-market-down)",
  sell: "var(--color-market-up)",
  hold: "var(--color-warning)",
  wait: "var(--color-market-flat)",
} as const

/** Risk level colors */
export const RISK_COLORS = {
  low: "var(--color-market-down)",
  medium: "var(--color-warning)",
  high: "var(--color-market-up)",
} as const

/** Chinese labels for board types */
export const BOARD_LABELS: Record<string, string> = {
  main: "主板",
  chinext: "创业板",
  star: "科创板",
}

/** Chinese labels for signal types */
export const SIGNAL_LABELS: Record<string, string> = {
  buy: "买入",
  sell: "卖出",
  hold: "持有",
  wait: "观望",
}

/** Chinese labels for risk levels */
export const RISK_LABELS: Record<string, string> = {
  low: "低风险",
  medium: "中风险",
  high: "高风险",
}

/** Chinese labels for trend directions */
export const TREND_LABELS: Record<string, string> = {
  up: "上涨",
  down: "下跌",
  sideways: "横盘",
}

/** Chinese strategy names */
export const STRATEGY_LABELS: Record<string, string> = {
  trend_following: "趋势跟踪",
  mean_reversion: "均值回归",
  momentum: "动量策略",
}

/** AI/Sentiment color scheme */
export const AI_COLORS = {
  primary: "var(--color-agent)",
  secondary: "var(--color-agent-text)",
  accent: "var(--accent-agent)",
  gradient: "var(--accent-agent)",
} as const

/** Sentiment badge colors */
export const SENTIMENT_COLORS = {
  positive: "var(--color-market-up)",
  negative: "var(--color-market-down)",
  neutral: "var(--color-market-flat)",
} as const

/** Alert severity colors */
export const ALERT_COLORS = {
  critical: "var(--color-market-up)",
  warning: "var(--color-warning)",
  info: "var(--color-info)",
} as const

/** Confidence level labels */
export const CONFIDENCE_LABELS: Record<string, string> = {
  high: "高置信",
  medium: "中置信",
  low: "低置信",
}

/** AI signal labels */
export const AI_SIGNAL_LABELS: Record<string, string> = {
  bullish: "看涨",
  bearish: "看跌",
  neutral: "中性",
}

/** Portfolio health labels (Chinese) */
export const HEALTH_LABELS: Record<string, string> = {
  优秀: "优秀",
  良好: "良好",
  一般: "一般",
  较差: "较差",
  危险: "危险",
}

/** Portfolio health score color thresholds */
export const HEALTH_COLORS = {
  excellent: "var(--color-market-down)", // 80-100
  good: "var(--color-info)",            // 60-79
  fair: "var(--color-warning)",         // 40-59
  poor: "var(--color-market-up)",       // 0-39
} as const

/** Position action labels (Chinese) */
export const POSITION_ACTION_LABELS: Record<string, string> = {
  hold: "持有",
  reduce: "减仓",
  increase: "加仓",
  stop_loss: "止损",
  take_profit: "止盈",
}

/** Position action colors */
export const POSITION_ACTION_COLORS: Record<string, string> = {
  hold: "var(--color-market-flat)",
  reduce: "var(--color-warning)",
  increase: "var(--color-info)",
  stop_loss: "var(--color-market-up)",
  take_profit: "var(--color-market-down)",
}

/** Dragon tiger seat type labels */
export const SEAT_TYPE_LABELS: Record<string, string> = {
  机构: "机构",
  知名游资: "知名游资",
  普通营业部: "普通营业部",
}

/** Dragon tiger seat type icons (emoji) */
export const SEAT_TYPE_ICONS: Record<string, string> = {
  机构: "\uD83C\uDFDB\uFE0F",
  知名游资: "\uD83D\uDD25",
  普通营业部: "\uD83C\uDFE2",
}

/** Chart event type labels */
export const CHART_EVENT_LABELS: Record<string, string> = {
  news: "新闻",
  dragon_tiger: "龙虎榜",
  pattern: "K线形态",
  anomaly: "异动",
}
