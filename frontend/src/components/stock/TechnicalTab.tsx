import { useMemo, useState } from "react"
import { Loader2, ChevronDown, AlertCircle } from "lucide-react"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { useOHLCV, useIndicators, useIndicatorsFull, useSupportResistance } from "@/hooks/useStocks"
import { useChartEvents } from "@/hooks/useAnalysis"
import { useRealtimeSnapshot } from "@/hooks/useRealtimeSnapshot"
import { CandlestickChart } from "@/components/stock/CandlestickChart"
import { IndicatorsChart } from "@/components/stock/IndicatorsChart"
import { UnifiedIndicatorAnalysis } from "@/components/stock/UnifiedIndicatorAnalysis"
import { SupportResistanceCard } from "@/components/stock/SupportResistanceCard"
import { FundFlowCard } from "@/components/stock/FundFlowCard"
import { IntradayTradesCard } from "@/components/stock/IntradayTradesCard"
import { StockDragonTigerDeep } from "@/components/stock/StockDragonTigerDeep"
import { ChartEventTimeline } from "@/components/stock/ChartEventTimeline"
import type { RealtimeQuote } from "@/types/market"
import type { Position } from "@/types/portfolio"

const PERIOD_OPTIONS = [
  { label: "分时", value: "timeline" },
  { label: "1分", value: "1" },
  { label: "5分", value: "5" },
  { label: "15分", value: "15" },
  { label: "30分", value: "30" },
  { label: "日K", value: "daily" },
  { label: "周K", value: "weekly" },
  { label: "月K", value: "monthly" },
]

const RANGE_OPTIONS = [
  { label: "近7日", days: 7 },
  { label: "近30日", days: 30 },
  { label: "近60日", days: 60 },
  { label: "半年", days: 120 },
  { label: "全部", days: 0 },
]

/** Periods that support date range filtering */
const RANGE_ELIGIBLE = new Set(["daily", "weekly", "monthly"])

interface TechnicalTabProps {
  symbol: string
  realtimeQuote: RealtimeQuote | null
  currentPosition: Position | null
}

function SectionHeader({
  title,
  open,
  onToggle,
}: {
  title: string
  open: boolean
  onToggle: () => void
}) {
  return (
    <CollapsibleTrigger asChild onClick={onToggle}>
      <button className="flex w-full items-center justify-between rounded-lg border bg-card px-4 py-2.5 text-sm font-medium hover:bg-muted/50 transition-colors">
        {title}
        <ChevronDown
          className={`h-4 w-4 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
    </CollapsibleTrigger>
  )
}

export function TechnicalTab({ symbol, realtimeQuote }: TechnicalTabProps) {
  // --- Hooks that only fire when this tab is active ---
  const { data: indicators } = useIndicators(symbol)
  const { data: indicatorsFull } = useIndicatorsFull(symbol)
  const { data: srLevels } = useSupportResistance(symbol)
  const { data: chartEvents } = useChartEvents(symbol)
  const { data: realtimeSnapshot } = useRealtimeSnapshot(symbol)

  // --- Local state ---
  const [chartPeriod, setChartPeriod] = useState("daily")
  const [chartDays, setChartDays] = useState(0)
  const [indicatorsOpen, setIndicatorsOpen] = useState(false)
  const [tradingOpen, setTradingOpen] = useState(false)
  const [dragonTigerOpen, setDragonTigerOpen] = useState(false)

  const { data: ohlcv, isError: ohlcvError } = useOHLCV(symbol, chartPeriod)

  const filteredOhlcv = useMemo(() => {
    if (!ohlcv || ohlcv.length === 0) return ohlcv
    if (chartDays === 0 || !RANGE_ELIGIBLE.has(chartPeriod)) return ohlcv
    return ohlcv.slice(-chartDays)
  }, [ohlcv, chartDays, chartPeriod])

  const isTimelineMode = chartPeriod === "timeline"

  return (
    <div className="space-y-4">
      {/* ── Group 1: Chart (always visible) ── */}
      {/* Period selector */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1 rounded-lg border bg-card p-1">
          {PERIOD_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setChartPeriod(opt.value)}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                chartPeriod === opt.value
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        {RANGE_ELIGIBLE.has(chartPeriod) && (
          <div className="flex items-center gap-1 rounded-lg border bg-card p-1">
            {RANGE_OPTIONS.map((opt) => (
              <button
                key={opt.days}
                onClick={() => setChartDays(opt.days)}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  chartDays === opt.days
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* K-Line Chart */}
      {filteredOhlcv && filteredOhlcv.length > 0 ? (
        <CandlestickChart
          data={filteredOhlcv}
          indicatorsData={!isTimelineMode ? indicatorsFull : undefined}
          chartEvents={!isTimelineMode ? chartEvents?.events : undefined}
          srLevels={!isTimelineMode ? srLevels : undefined}
          timelineMode={isTimelineMode}
        />
      ) : ohlcvError ? (
        <div className="flex flex-col items-center justify-center h-[620px] text-muted-foreground gap-2">
          <AlertCircle className="h-8 w-8" />
          <span>{isTimelineMode ? "分时数据暂不可用（非交易时段或数据源异常）" : "图表数据暂不可用"}</span>
        </div>
      ) : (
        <div className="flex items-center justify-center h-[620px] text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin mr-2" />
          加载图表数据...
        </div>
      )}

      {chartEvents?.events && chartEvents.events.length > 0 && (
        <ChartEventTimeline events={chartEvents.events} />
      )}

      {/* ── Group 2: 技术指标分析 (collapsed by default) ── */}
      <Collapsible open={indicatorsOpen} onOpenChange={setIndicatorsOpen}>
        <SectionHeader title="技术指标分析" open={indicatorsOpen} onToggle={() => setIndicatorsOpen(!indicatorsOpen)} />
        <CollapsibleContent className="space-y-4 pt-3">
          {indicatorsFull && indicatorsFull.length > 0 && (
            <IndicatorsChart data={indicatorsFull} />
          )}
          <UnifiedIndicatorAnalysis symbol={symbol} indicators={indicators} />
        </CollapsibleContent>
      </Collapsible>

      {/* ── Group 3: 盘口与资金 (collapsed by default) ── */}
      <Collapsible open={tradingOpen} onOpenChange={setTradingOpen}>
        <SectionHeader title="盘口与资金" open={tradingOpen} onToggle={() => setTradingOpen(!tradingOpen)} />
        <CollapsibleContent className="pt-3">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <IntradayTradesCard symbol={symbol} snapshot={realtimeSnapshot} />
            {srLevels && (
              <SupportResistanceCard levels={srLevels} symbol={symbol} realtimeQuote={realtimeQuote} />
            )}
            <FundFlowCard symbol={symbol} snapshot={realtimeSnapshot} />
          </div>
        </CollapsibleContent>
      </Collapsible>

      {/* ── Group 4: 龙虎榜 (collapsed by default) ── */}
      <Collapsible open={dragonTigerOpen} onOpenChange={setDragonTigerOpen}>
        <SectionHeader title="龙虎榜" open={dragonTigerOpen} onToggle={() => setDragonTigerOpen(!dragonTigerOpen)} />
        <CollapsibleContent className="pt-3">
          <StockDragonTigerDeep symbol={symbol} />
        </CollapsibleContent>
      </Collapsible>

    </div>
  )
}
