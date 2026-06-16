import { useMemo } from "react"
import { BrowserRouter, Routes, Route } from "react-router-dom"
import { QueryClient, QueryClientProvider, QueryCache, MutationCache } from "@tanstack/react-query"
import { toast } from "sonner"
import { Layout } from "@/components/layout/Layout"
import CommandPalette from "@/components/stock/CommandPalette"
import { OnboardingDialog } from "@/components/onboarding/OnboardingDialog"
import { DisclaimerDialog } from "@/components/onboarding/DisclaimerDialog"
import { useRealtimeQuotes, useMarketIndices } from "@/hooks/useMarket"
import { useRealtimeWS } from "@/hooks/useRealtimeWS"
import { useWatchlist } from "@/hooks/useStocks"
import { usePortfolio } from "@/hooks/usePortfolio"
import Dashboard from "@/pages/Dashboard"
import StockDetail from "@/pages/StockDetail"
import Settings from "@/pages/Settings"
import Market from "@/pages/Market"
import Portfolio from "@/pages/Portfolio"
import Intelligence from "@/pages/Intelligence"
import IntelligenceHub from "@/pages/IntelligenceHub"
import IntelReports from "@/pages/IntelReports"
import Recommendations from "@/pages/Recommendations"
import CIODashboard from "@/pages/CIODashboard"
import AgentDashboard from "@/pages/AgentDashboard"
import TradeHistory from "@/pages/TradeHistory"

/** Global realtime provider — WS push (auto-degrades to SSE), with HTTP polling safety net. */
function GlobalRealtimeProvider() {
  const { data: watchlist } = useWatchlist()
  const { positions } = usePortfolio()
  const symbols = useMemo(() => {
    const set = new Set<string>()
    watchlist?.forEach((w) => set.add(w.symbol))
    positions?.forEach((p) => set.add(p.symbol))
    return Array.from(set)
  }, [watchlist, positions])

  // WS push (auto-degrades to SSE)
  useRealtimeWS(symbols)
  // HTTP polling safety net (30s fallback when WS+SSE both down)
  useRealtimeQuotes()
  useMarketIndices()
  return null
}

function extractMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (query.meta?.skipGlobalError) return
      // Only toast on background refresh failures (user already sees stale data)
      if (query.state.data !== undefined) {
        toast.error(`数据更新失败: ${extractMessage(error)}`)
      }
    },
  }),
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => {
      if (mutation.meta?.skipGlobalError) return
      toast.error(`操作失败: ${extractMessage(error)}`)
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <GlobalRealtimeProvider />
        <CommandPalette />
        <OnboardingDialog />
        <DisclaimerDialog />
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/market" element={<Market />} />
            <Route path="/intelligence" element={<Intelligence />} />
            <Route path="/info-hub" element={<IntelligenceHub />} />
            <Route path="/recommendations" element={<Recommendations />} />
            <Route path="/cio" element={<CIODashboard />} />
            <Route path="/agent" element={<AgentDashboard />} />
            <Route path="/trades" element={<TradeHistory />} />
            <Route path="/reports" element={<IntelReports />} />
            <Route path="/stock/:symbol" element={<StockDetail />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
