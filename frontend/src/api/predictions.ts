import client from "./client"
import type {
  PredictionResult,
  EnhancedPredictionResult,
  ComparisonPredictionResult,
  DataSource,
} from "@/types/prediction"

export async function predict(symbol: string): Promise<PredictionResult> {
  const { data } = await client.post<PredictionResult>(`/predict/${symbol}`)
  return data
}

export async function predictEnhanced(
  symbol: string,
  sources: DataSource[],
): Promise<EnhancedPredictionResult> {
  const { data } = await client.post<EnhancedPredictionResult>(
    `/predict/${symbol}/enhanced`,
    { sources },
  )
  return data
}

export async function predictComparison(
  symbols: string[],
  sources: DataSource[],
): Promise<ComparisonPredictionResult> {
  const { data } = await client.post<ComparisonPredictionResult>(
    "/predict/compare",
    { symbols, sources },
  )
  return data
}
