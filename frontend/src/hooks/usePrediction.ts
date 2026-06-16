import { useMutation } from "@tanstack/react-query"
import { predict, predictEnhanced, predictComparison } from "@/api/predictions"
import type { DataSource } from "@/types/prediction"

export function usePrediction() {
  return useMutation({
    mutationFn: (symbol: string) => predict(symbol),
  })
}

export function useEnhancedPrediction() {
  return useMutation({
    mutationFn: ({ symbol, sources }: { symbol: string; sources: DataSource[] }) =>
      predictEnhanced(symbol, sources),
  })
}

export function useComparisonPrediction() {
  return useMutation({
    mutationFn: ({ symbols, sources }: { symbols: string[]; sources: DataSource[] }) =>
      predictComparison(symbols, sources),
  })
}
