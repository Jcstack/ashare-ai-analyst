import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Format a large number with 万/亿 suffix (Chinese convention) */
export function formatVolume(vol: number): string {
  if (Number.isNaN(vol)) return "--"
  if (vol >= 100000000) return (vol / 100000000).toFixed(2) + "亿"
  if (vol >= 10000) return (vol / 10000).toFixed(2) + "万"
  return vol.toLocaleString()
}

/** Format a large number (e.g. fund flow) with 万/亿 suffix, preserving sign */
export function formatLargeNumber(val: number): string {
  if (Number.isNaN(val)) return "--"
  const abs = Math.abs(val)
  if (abs >= 100000000) return (val / 100000000).toFixed(2) + "亿"
  if (abs >= 10000) return (val / 10000).toFixed(1) + "万"
  return val.toFixed(0)
}

/** Format price with 2 decimal places */
export function formatPrice(price: number | null | undefined): string {
  if (price == null || Number.isNaN(price)) return "--"
  return price.toFixed(2)
}

/** Format percentage with sign and 2 decimals */
export function formatPercent(pct: number | null | undefined): string {
  if (pct == null || Number.isNaN(pct)) return "--"
  const sign = pct > 0 ? "+" : ""
  return `${sign}${pct.toFixed(2)}%`
}

/** Get price direction: "up" | "down" | "flat" */
export function getPriceDirection(change: number | null | undefined): "up" | "down" | "flat" {
  if (change == null || Number.isNaN(change) || change === 0) return "flat"
  return change > 0 ? "up" : "down"
}
