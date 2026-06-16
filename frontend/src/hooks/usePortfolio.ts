import { useCallback } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import type { BoardType, Portfolio, Position, PortfolioSummary, PositionWithPnL } from "@/types/portfolio"
import type { RealtimeQuote } from "@/types/market"
import {
  loadPortfolioFromServer,
  addPosition as addPositionApi,
  updatePosition as updatePositionApi,
  removePosition as removePositionApi,
  liquidatePosition as liquidatePositionApi,
  savePortfolioToServer,
} from "@/api/portfolio"

// ---------------------------------------------------------------------------
// Pure utility functions (unchanged)
// ---------------------------------------------------------------------------

/** Detect board type from A-share stock code prefix. */
export function detectBoard(symbol: string): BoardType {
  if (symbol.startsWith("688")) return "star"
  if (symbol.startsWith("3")) return "chinext"
  return "main"
}

/** Compute portfolio summary by merging with realtime quotes. */
export function computePortfolioSummary(
  positions: Position[],
  realtimeMap: Map<string, RealtimeQuote>,
): PortfolioSummary {
  let totalCost = 0
  let totalMarketValue = 0

  const enriched: PositionWithPnL[] = positions.map((pos) => {
    const rt = realtimeMap.get(pos.symbol)
    const currentPrice = rt?.price ?? null
    const todayPctChange = rt?.pct_change ?? null
    const effectivePrice = currentPrice ?? pos.costPrice
    const marketValue = effectivePrice * pos.shares
    const cost = pos.costPrice * pos.shares
    const pnl = marketValue - cost
    const pnlPercent = cost > 0 ? (pnl / cost) * 100 : 0

    totalCost += cost
    totalMarketValue += marketValue

    return {
      ...pos,
      currentPrice,
      todayPctChange,
      marketValue,
      pnl,
      pnlPercent,
    }
  })

  const totalPnL = totalMarketValue - totalCost
  const totalPnLPercent = totalCost > 0 ? (totalPnL / totalCost) * 100 : 0

  return {
    positionCount: positions.length,
    totalCost,
    totalMarketValue,
    totalPnL,
    totalPnLPercent,
    positions: enriched,
  }
}

// ---------------------------------------------------------------------------
// Hook — server-first with React Query
// ---------------------------------------------------------------------------

export function usePortfolio() {
  const queryClient = useQueryClient()

  const { data: portfolio, isLoading } = useQuery<Portfolio>({
    queryKey: ["portfolio"],
    queryFn: loadPortfolioFromServer,
    staleTime: 30_000,
    placeholderData: { version: 1, updatedAt: "", positions: [] },
  })

  const positions = portfolio?.positions ?? []

  const addMutation = useMutation({
    mutationFn: (pos: Omit<Position, "id">) =>
      addPositionApi({
        symbol: pos.symbol,
        name: pos.name,
        board: pos.board,
        costPrice: pos.costPrice,
        shares: pos.shares,
        buyDate: pos.buyDate,
        validateCapital: true,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolio"] })
      queryClient.invalidateQueries({ queryKey: ["capital"] })
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, updates }: { id: string; updates: Partial<Position> }) =>
      updatePositionApi(id, updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolio"] })
    },
  })

  const removeMutation = useMutation({
    mutationFn: (id: string) => removePositionApi(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolio"] })
    },
  })

  const liquidateMutation = useMutation({
    mutationFn: ({ pos, currentPrice }: { pos: Position; currentPrice: number }) =>
      liquidatePositionApi({
        symbol: pos.symbol,
        stock_name: pos.name,
        shares: pos.shares,
        price: currentPrice,
        position_id: pos.id,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolio"] })
      queryClient.invalidateQueries({ queryKey: ["capital"] })
    },
  })

  const clearAllMutation = useMutation({
    mutationFn: () =>
      savePortfolioToServer({ version: 1, updatedAt: new Date().toISOString(), positions: [] }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolio"] })
      queryClient.invalidateQueries({ queryKey: ["capital"] })
    },
  })

  const addPosition = useCallback(
    (pos: Omit<Position, "id">) => addMutation.mutateAsync(pos),
    [addMutation],
  )

  const updatePosition = useCallback(
    (id: string, updates: Partial<Position>) => {
      updateMutation.mutate({ id, updates })
    },
    [updateMutation],
  )

  const removePosition = useCallback(
    (id: string) => {
      removeMutation.mutate(id)
    },
    [removeMutation],
  )

  const liquidatePosition = useCallback(
    (pos: Position, currentPrice: number) =>
      liquidateMutation.mutateAsync({ pos, currentPrice }),
    [liquidateMutation],
  )

  const clearAll = useCallback(() => {
    clearAllMutation.mutate()
  }, [clearAllMutation])

  return {
    portfolio: portfolio ?? { version: 1, updatedAt: "", positions: [] },
    positions,
    isEmpty: positions.length === 0,
    isLoading,
    addPosition,
    updatePosition,
    removePosition,
    liquidatePosition,
    clearAll,
    addMutation,
  }
}
