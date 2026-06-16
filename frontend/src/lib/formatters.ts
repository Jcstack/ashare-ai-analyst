/**
 * v10 Unified Number Formatting Utilities
 *
 * Standard rules:
 * - PnL: always show sign (+/-), thousands separator, 2 decimal places
 * - Percent: always show sign, 2 decimal places
 * - Volume: >= 1亿 show as X.XX亿, >= 1万 show as X.XX万
 * - Price: 2 decimal places, no sign
 * - Null/undefined → "--"
 */

const FALLBACK = "--"

/** Format a price value: 2 decimal places, no sign. */
export function formatPrice(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return FALLBACK
  return value.toFixed(2)
}

/** Format a PnL (profit/loss) value: always show sign, thousands separator. */
export function formatPnL(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return FALLBACK
  const sign = value > 0 ? "+" : ""
  const formatted = Math.abs(value) >= 1000
    ? Math.abs(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : Math.abs(value).toFixed(2)
  return value < 0 ? `-${formatted}` : `${sign}${formatted}`
}

/** Format a percentage value: always show sign, 2 decimal places. */
export function formatPercent(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return FALLBACK
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(2)}%`
}

/** Format a percentage change for display in badges: (+3.25%) or (-1.50%). */
export function formatPctChange(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return FALLBACK
  const sign = value > 0 ? "+" : ""
  return `(${sign}${value.toFixed(2)}%)`
}

/** Format volume: >= 1亿 → X.XX亿, >= 1万 → X.XX万, otherwise raw number. */
export function formatVolume(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return FALLBACK
  const abs = Math.abs(value)
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(value / 1e4).toFixed(2)}万`
  return value.toLocaleString("zh-CN")
}

/** Format monetary amount: >= 1亿 → X.XX亿, >= 1万 → X.XX万, otherwise 2 decimal places. */
export function formatAmount(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return FALLBACK
  const abs = Math.abs(value)
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(value / 1e4).toFixed(2)}万`
  return value.toFixed(2)
}

// ---------------------------------------------------------------------------
// Time Formatting — all parse via `new Date()` which auto-converts UTC → local
// ---------------------------------------------------------------------------

const TIME_FALLBACK = ""

/** Format ISO timestamp → "MM-DD HH:MM" in browser local time. */
export function formatTime(iso: string | null | undefined): string {
  if (!iso) return TIME_FALLBACK
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso
    const mm = String(d.getMonth() + 1).padStart(2, "0")
    const dd = String(d.getDate()).padStart(2, "0")
    const hh = String(d.getHours()).padStart(2, "0")
    const min = String(d.getMinutes()).padStart(2, "0")
    return `${mm}-${dd} ${hh}:${min}`
  } catch {
    return iso
  }
}

/** Format ISO timestamp → "YYYY-MM-DD HH:MM:SS" in browser local time. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return TIME_FALLBACK
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso
    const y = d.getFullYear()
    const mm = String(d.getMonth() + 1).padStart(2, "0")
    const dd = String(d.getDate()).padStart(2, "0")
    const hh = String(d.getHours()).padStart(2, "0")
    const min = String(d.getMinutes()).padStart(2, "0")
    const ss = String(d.getSeconds()).padStart(2, "0")
    return `${y}-${mm}-${dd} ${hh}:${min}:${ss}`
  } catch {
    return iso
  }
}

/** Format ISO timestamp → "HH:MM" in browser local time. */
export function formatTimeShort(iso: string | null | undefined): string {
  if (!iso) return TIME_FALLBACK
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso
    const hh = String(d.getHours()).padStart(2, "0")
    const min = String(d.getMinutes()).padStart(2, "0")
    return `${hh}:${min}`
  } catch {
    return iso
  }
}

/** Get the semantic color class for a numeric value: text-up / text-down / text-flat. */
export function pnlColorClass(value: number | null | undefined): string {
  if (value == null || value === 0) return "text-market-flat"
  return value > 0 ? "text-market-up" : "text-market-down"
}
