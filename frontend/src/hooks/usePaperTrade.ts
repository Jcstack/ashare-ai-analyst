import { useCallback, useSyncExternalStore } from "react"
import type { PaperPortfolio, PaperPosition, PaperClosedTrade } from "@/types/backtest"

const STORAGE_KEY = "astock-paper-trade"

const DEFAULT_CAPITAL = 1_000_000

// ---------------------------------------------------------------------------
// External store for cross-tab reactivity
// ---------------------------------------------------------------------------

let listeners: Array<() => void> = []

function subscribe(listener: () => void) {
  listeners = [...listeners, listener]

  function handleStorage(e: StorageEvent) {
    if (e.key === STORAGE_KEY) listener()
  }
  window.addEventListener("storage", handleStorage)

  return () => {
    listeners = listeners.filter((l) => l !== listener)
    window.removeEventListener("storage", handleStorage)
  }
}

function emitChange() {
  for (const listener of listeners) listener()
}

function getSnapshot(): string {
  return localStorage.getItem(STORAGE_KEY) ?? ""
}

function getServerSnapshot(): string {
  return ""
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function readPortfolio(): PaperPortfolio {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return createEmpty()
    const parsed = JSON.parse(raw) as PaperPortfolio
    if (parsed.version !== 1) return createEmpty()
    return parsed
  } catch {
    return createEmpty()
  }
}

function createEmpty(): PaperPortfolio {
  return {
    version: 1,
    updatedAt: new Date().toISOString(),
    initial_capital: DEFAULT_CAPITAL,
    cash: DEFAULT_CAPITAL,
    positions: [],
    closed_trades: [],
  }
}

function writePortfolio(portfolio: PaperPortfolio) {
  portfolio.updatedAt = new Date().toISOString()
  localStorage.setItem(STORAGE_KEY, JSON.stringify(portfolio))
  emitChange()
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function usePaperTrade() {
  const raw = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)

  const portfolio: PaperPortfolio = raw
    ? (() => {
        try {
          return JSON.parse(raw) as PaperPortfolio
        } catch {
          return createEmpty()
        }
      })()
    : createEmpty()

  const { positions, closed_trades: closedTrades, cash } = portfolio
  const isEmpty = positions.length === 0 && closedTrades.length === 0

  const openPosition = useCallback(
    (pos: Omit<PaperPosition, "id">) => {
      const current = readPortfolio()
      const cost = pos.entry_price * pos.shares
      if (cost > current.cash) return // Insufficient funds
      const id = `${pos.symbol}-${Date.now()}`
      current.positions.push({ ...pos, id })
      current.cash -= cost
      writePortfolio(current)
    },
    [],
  )

  const closePosition = useCallback(
    (id: string, exitPrice: number) => {
      const current = readPortfolio()
      const idx = current.positions.findIndex((p) => p.id === id)
      if (idx < 0) return

      const pos = current.positions[idx]
      const exitValue = exitPrice * pos.shares
      const entryValue = pos.entry_price * pos.shares
      const pnl = exitValue - entryValue
      const pnlPct = entryValue > 0 ? (pnl / entryValue) * 100 : 0

      const closedTrade: PaperClosedTrade = {
        id: `closed-${Date.now()}`,
        symbol: pos.symbol,
        name: pos.name,
        strategy_key: pos.strategy_key,
        entry_price: pos.entry_price,
        exit_price: exitPrice,
        shares: pos.shares,
        entry_date: pos.entry_date,
        exit_date: new Date().toISOString().slice(0, 10),
        pnl: Math.round(pnl * 100) / 100,
        pnl_pct: Math.round(pnlPct * 100) / 100,
      }

      current.positions.splice(idx, 1)
      current.closed_trades.push(closedTrade)
      current.cash += exitValue
      writePortfolio(current)
    },
    [],
  )

  const clearAll = useCallback(() => {
    writePortfolio(createEmpty())
  }, [])

  // Computed values
  const positionsValue = positions.reduce((sum, p) => sum + p.entry_price * p.shares, 0)
  const totalCapital = cash + positionsValue
  const totalPnL = totalCapital - portfolio.initial_capital
  const totalPnLPct = portfolio.initial_capital > 0 ? (totalPnL / portfolio.initial_capital) * 100 : 0

  return {
    portfolio,
    positions,
    closedTrades,
    cash,
    isEmpty,
    totalCapital,
    positionsValue,
    totalPnL,
    totalPnLPct,
    openPosition,
    closePosition,
    clearAll,
  }
}
