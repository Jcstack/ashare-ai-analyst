/**
 * v10 Unified Chart Theme Configuration
 *
 * Shared visual config for Recharts and Lightweight Charts.
 * All chart components should reference these constants instead
 * of hardcoding colors, fonts, or sizes.
 */

// ── Semantic Colors (CSS variable references) ──────────────────────────────

export const CHART_COLORS = {
  /** Candlestick / price up (A-share: red) */
  up: "var(--semantic-up)",
  /** Candlestick / price down (A-share: green) */
  down: "var(--semantic-down)",
  /** No change / flat */
  flat: "var(--semantic-flat)",
  /** Volume bars (up) — lower opacity */
  volumeUp: "rgba(229, 83, 75, 0.3)",
  /** Volume bars (down) — lower opacity */
  volumeDown: "rgba(63, 185, 80, 0.3)",
} as const

/** Moving average overlay colors */
export const MA_COLORS = {
  MA5: "#e5a04b",
  MA10: "#539bf5",
  MA20: "#b083e0",
  MA60: "#e5534b",
} as const

/** Indicator line colors */
export const INDICATOR_COLORS = {
  macdLine: "#e5534b",
  macdSignal: "#3fb950",
  macdHistogram: "var(--text-tertiary)",
  rsi: "#b083e0",
  kdjK: "#e5a04b",
  kdjD: "#539bf5",
  kdjJ: "#b083e0",
  bollUpper: "#539bf5",
  bollMiddle: "#e5a04b",
  bollLower: "#539bf5",
  obv: "#539bf5",
} as const

/** Chart event marker colors */
export const EVENT_COLORS = {
  news: "#539bf5",
  dragon_tiger: "#e5a04b",
  pattern: "#b083e0",
  anomaly: "#d29922",
} as const

/** Support/Resistance line colors */
export const SR_COLORS = {
  support: "rgba(63, 185, 80, 0.6)",
  resistance: "rgba(229, 83, 75, 0.6)",
} as const

// ── Grid & Axis Config ─────────────────────────────────────────────────────

export const GRID_CONFIG = {
  stroke: "var(--border-subtle)",
  strokeOpacity: 0.06,
  strokeDasharray: "2 6",
} as const

export const AXIS_CONFIG = {
  tickFontSize: 10,
  tickFontFamily: "var(--font-mono)",
  tickFill: "var(--text-tertiary)",
  axisLine: false,
  tickLine: false,
} as const

// ── Tooltip Config ─────────────────────────────────────────────────────────

export const TOOLTIP_STYLE = {
  backgroundColor: "var(--bg-elevated)",
  borderColor: "var(--border-default)",
  borderWidth: 1,
  borderRadius: 6,
  fontSize: 12,
  color: "var(--text-primary)",
  labelColor: "var(--text-secondary)",
  padding: "8px 12px",
} as const

/** Recharts tooltip contentStyle object */
export const rechartsTooltipStyle: React.CSSProperties = {
  background: TOOLTIP_STYLE.backgroundColor,
  border: `${TOOLTIP_STYLE.borderWidth}px solid ${TOOLTIP_STYLE.borderColor}`,
  borderRadius: TOOLTIP_STYLE.borderRadius,
  fontSize: TOOLTIP_STYLE.fontSize,
  color: TOOLTIP_STYLE.color,
  padding: TOOLTIP_STYLE.padding,
  boxShadow: "none",
}

// ── Reference Area & Line Config ───────────────────────────────────────────

export const REFERENCE_AREA = {
  /** RSI overbought zone (70-100) */
  overbought: { fill: "var(--semantic-up)", fillOpacity: 0.06 },
  /** RSI oversold zone (0-30) */
  oversold: { fill: "var(--semantic-down)", fillOpacity: 0.06 },
} as const

export const REFERENCE_LINE = {
  strokeDasharray: "3 3",
  strokeOpacity: 0.5,
} as const

// ── Standard Chart Heights ─────────────────────────────────────────────────

export const CHART_HEIGHTS = {
  compact: 120,
  standard: 160,
  hero: 220,
} as const

// ── Lightweight Charts Config ──────────────────────────────────────────────

export const lwcLayoutConfig = {
  background: { color: "transparent" },
  textColor: "var(--text-tertiary)",
  fontSize: 11,
  fontFamily: "var(--font-mono)",
} as const

export const lwcGridConfig = {
  vertLines: { color: "rgba(197, 203, 206, 0.06)" },
  horzLines: { color: "rgba(197, 203, 206, 0.06)" },
} as const

export const lwcCandlestickColors = {
  upColor: "#e5534b",
  downColor: "#3fb950",
  borderUpColor: "#e5534b",
  borderDownColor: "#3fb950",
  wickUpColor: "#e5534b",
  wickDownColor: "#3fb950",
} as const

export const lwcScaleConfig = {
  rightPriceScale: {
    borderColor: "rgba(197, 203, 206, 0.15)",
    scaleMargins: { top: 0.08, bottom: 0.02 },
  },
  timeScale: {
    borderColor: "rgba(197, 203, 206, 0.15)",
  },
} as const

// ── Price Flash Animation ──────────────────────────────────────────────────

export const FLASH_COLORS = {
  up: "rgba(229, 83, 75, 0.08)",
  down: "rgba(63, 185, 80, 0.08)",
  duration: 800,
} as const
