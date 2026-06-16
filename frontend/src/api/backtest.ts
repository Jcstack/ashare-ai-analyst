import client from "./client"
import type {
  StrategyInfo,
  BacktestRequest,
  BacktestResponse,
  BacktestInterpretRequest,
  BacktestInterpretResult,
  BacktestRequestV2,
  BacktestResponseV2,
  StrategyMetadata,
  NLStrategyRequest,
  NLStrategyResult,
  AIOptimizationRequest,
  AIOptimizationResult,
  AIAttributionRequest,
  AIAttributionResult,
  LatestSignalItem,
} from "@/types/backtest"

export async function getStrategies(): Promise<StrategyInfo[]> {
  const { data } = await client.get<StrategyInfo[]>("/strategies")
  return data
}

export async function runBacktest(req: BacktestRequest): Promise<BacktestResponse> {
  const { data } = await client.post<BacktestResponse>("/backtest", req)
  return data
}

export async function interpretBacktest(req: BacktestInterpretRequest): Promise<BacktestInterpretResult> {
  const { data } = await client.post<BacktestInterpretResult>("/backtest/ai-interpret", req)
  return data
}

export async function runBacktestV2(req: BacktestRequestV2): Promise<BacktestResponseV2> {
  const { data } = await client.post<BacktestResponseV2>("/backtest/v2", req)
  return data
}

export async function getStrategyMetadata(key: string): Promise<StrategyMetadata> {
  const { data } = await client.get<StrategyMetadata>(`/strategies/${key}/metadata`)
  return data
}

export async function createStrategyFromNL(req: NLStrategyRequest): Promise<NLStrategyResult> {
  const { data } = await client.post<NLStrategyResult>("/strategy-lab/nl-create", req)
  return data
}

export async function aiOptimizeParams(req: AIOptimizationRequest): Promise<AIOptimizationResult> {
  const { data } = await client.post<AIOptimizationResult>("/strategy-lab/ai-optimize", req)
  return data
}

export async function aiAttribution(req: AIAttributionRequest): Promise<AIAttributionResult> {
  const { data } = await client.post<AIAttributionResult>("/strategy-lab/ai-attribution", req)
  return data
}

export async function getLatestSignals(symbol: string): Promise<LatestSignalItem[]> {
  const { data } = await client.get<LatestSignalItem[]>(`/strategy-lab/latest-signals/${symbol}`)
  return data
}

export async function checkPaperTradeSignals(positions: Array<{ symbol: string; strategy_key: string }>): Promise<LatestSignalItem[]> {
  const { data } = await client.post<LatestSignalItem[]>("/strategy-lab/check-signals", { positions })
  return data
}
