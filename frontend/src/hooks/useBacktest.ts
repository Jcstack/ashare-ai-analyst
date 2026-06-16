import { useQuery, useMutation } from "@tanstack/react-query"
import {
  getStrategies,
  runBacktest,
  interpretBacktest,
  runBacktestV2,
  getStrategyMetadata,
  createStrategyFromNL,
  aiOptimizeParams,
  aiAttribution,
  getLatestSignals,
} from "@/api/backtest"
import type {
  BacktestRequest,
  BacktestInterpretRequest,
  BacktestRequestV2,
  NLStrategyRequest,
  AIOptimizationRequest,
  AIAttributionRequest,
} from "@/types/backtest"

export function useStrategies() {
  return useQuery({
    queryKey: ["strategies"],
    queryFn: getStrategies,
  })
}

export function useBacktestRun() {
  return useMutation({
    mutationFn: (req: BacktestRequest) => runBacktest(req),
  })
}

export function useBacktestInterpret() {
  return useMutation({
    mutationFn: (req: BacktestInterpretRequest) => interpretBacktest(req),
  })
}

export function useBacktestRunV2() {
  return useMutation({
    mutationFn: (req: BacktestRequestV2) => runBacktestV2(req),
  })
}

export function useStrategyMetadata(key: string) {
  return useQuery({
    queryKey: ["strategy-metadata", key],
    queryFn: () => getStrategyMetadata(key),
    enabled: !!key,
  })
}

export function useNLStrategyCreate() {
  return useMutation({
    mutationFn: (req: NLStrategyRequest) => createStrategyFromNL(req),
  })
}

export function useAIOptimize() {
  return useMutation({
    mutationFn: (req: AIOptimizationRequest) => aiOptimizeParams(req),
  })
}

export function useAIAttribution() {
  return useMutation({
    mutationFn: (req: AIAttributionRequest) => aiAttribution(req),
  })
}

export function useLatestSignals(symbol: string) {
  return useQuery({
    queryKey: ["latest-signals", symbol],
    queryFn: () => getLatestSignals(symbol),
    enabled: !!symbol,
    staleTime: 60_000,
  })
}
