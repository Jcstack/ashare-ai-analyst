import { useQuery } from "@tanstack/react-query"
import client from "@/api/client"

export interface FundFlowItem {
  date: string
  close: number | null
  pct_change: number | null
  main_net: number | null
  main_net_pct: number | null
  super_large_net: number | null
  large_net: number | null
  medium_net: number | null
  small_net: number | null
}

export interface SRAnalysis {
  status: string
  symbol: string
  summary: string
  key_levels: { price: number; type: string; strength: string; comment: string }[]
  advice: string
  risk_warnings: string[]
  generated_at: string | null
}

async function fetchFundFlow(symbol: string): Promise<FundFlowItem[]> {
  const { data } = await client.get<FundFlowItem[]>(`/stock/${symbol}/fund-flow`)
  return data
}

async function fetchIntradayFundFlow(symbol: string): Promise<FundFlowItem[]> {
  const { data } = await client.get<FundFlowItem[]>(`/stock/${symbol}/fund-flow/intraday`)
  return data
}

export interface FundFlowDetail {
  symbol: string
  name?: string
  price?: number | null
  pct_change?: number | null
  inflow?: number | null
  outflow?: number | null
  net?: number | null
  amount?: number | null
}

async function fetchFundFlowDetail(symbol: string): Promise<FundFlowDetail> {
  const { data } = await client.get<FundFlowDetail>(`/stock/${symbol}/fund-flow/detail`)
  return data
}

export interface ComprehensiveAnalysis {
  symbol: string
  signal: string
  confidence: number
  summary: string
  points: string[]
  risks: string[]
  generated_at?: string
}

async function fetchComprehensiveAnalysis(symbol: string): Promise<ComprehensiveAnalysis> {
  const { data } = await client.get<ComprehensiveAnalysis>(`/stock/${symbol}/comprehensive-analysis`)
  return data
}

async function fetchSRAnalysis(symbol: string): Promise<SRAnalysis> {
  const { data } = await client.get<SRAnalysis>(`/stock/${symbol}/sr-analysis`)
  return data
}

export function useFundFlow(symbol: string) {
  return useQuery({
    queryKey: ["fund-flow", symbol],
    queryFn: () => fetchFundFlow(symbol),
    enabled: !!symbol,
    staleTime: 10 * 60_000, // 10 minutes
  })
}

export function useIntradayFundFlow(symbol: string) {
  return useQuery({
    queryKey: ["fund-flow-intraday", symbol],
    queryFn: () => fetchIntradayFundFlow(symbol),
    enabled: !!symbol,
    staleTime: 60_000, // 1 minute
    refetchInterval: 60_000,
    retry: 2,
  })
}

export function useFundFlowDetail(symbol: string) {
  return useQuery({
    queryKey: ["fund-flow-detail", symbol],
    queryFn: () => fetchFundFlowDetail(symbol),
    enabled: !!symbol,
    staleTime: 60_000, // 1 minute
    refetchInterval: 60_000,
    retry: 2,
  })
}

export function useComprehensiveAnalysis(symbol: string) {
  return useQuery({
    queryKey: ["comprehensive-analysis", symbol],
    queryFn: () => fetchComprehensiveAnalysis(symbol),
    enabled: !!symbol,
    staleTime: 5 * 60_000, // 5 minutes
    retry: 1,
  })
}

export function useSRAnalysis(symbol: string) {
  return useQuery({
    queryKey: ["sr-analysis", symbol],
    queryFn: () => fetchSRAnalysis(symbol),
    enabled: !!symbol,
    staleTime: 30 * 60_000, // 30 minutes
    retry: 1,
  })
}
