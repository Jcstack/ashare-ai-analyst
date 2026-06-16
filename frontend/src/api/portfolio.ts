import client from "./client"
import type { Portfolio, PortfolioDiagnosis, PositionWithPnL } from "@/types/portfolio"

export interface DiagnoseRequest {
  positions: {
    symbol: string
    name: string
    board: string
    cost_price: number
    shares: number
    buy_date: string | null
    current_price: number | null
    pnl: number | null
    pnl_percent: number | null
  }[]
}

export async function diagnosePortfolio(req: DiagnoseRequest): Promise<PortfolioDiagnosis> {
  const { data } = await client.post<PortfolioDiagnosis>("/portfolio/diagnose", req)
  return data
}

/** Build diagnosis request from enriched positions */
export function buildDiagnoseRequest(positions: PositionWithPnL[]): DiagnoseRequest {
  return {
    positions: positions.map((p) => ({
      symbol: p.symbol,
      name: p.name,
      board: p.board,
      cost_price: p.costPrice,
      shares: p.shares,
      buy_date: p.buyDate || null,
      current_price: p.currentPrice,
      pnl: p.pnl,
      pnl_percent: p.pnlPercent,
    })),
  }
}

// ---------------------------------------------------------------------------
// Position liquidation (clear position + recover capital)
// ---------------------------------------------------------------------------

export interface LiquidatePositionRequest {
  symbol: string
  stock_name: string
  shares: number
  price: number
  position_id: string
}

export async function liquidatePosition(req: LiquidatePositionRequest) {
  const { data } = await client.post("/portfolio/positions/liquidate", req)
  return data
}

// ---------------------------------------------------------------------------
// Portfolio persistence (backend sync)
// ---------------------------------------------------------------------------

export async function loadPortfolioFromServer(): Promise<Portfolio> {
  const { data } = await client.get<Portfolio>("/portfolio")
  return data
}

export async function savePortfolioToServer(portfolio: Portfolio): Promise<void> {
  await client.put("/portfolio", portfolio)
}

// ---------------------------------------------------------------------------
// Position CRUD (granular server-first operations)
// ---------------------------------------------------------------------------

export interface AddPositionRequest {
  symbol: string
  name: string
  board: string
  costPrice: number
  shares: number
  buyDate: string
  note?: string
  validateCapital?: boolean
}

export async function addPosition(req: AddPositionRequest) {
  const { data } = await client.post("/portfolio/positions", req)
  return data
}

export async function updatePosition(id: string, updates: Record<string, unknown>) {
  const { data } = await client.put(`/portfolio/positions/${id}`, updates)
  return data
}

export async function removePosition(id: string) {
  const { data } = await client.delete(`/portfolio/positions/${id}`)
  return data
}
