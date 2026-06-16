import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import { DollarSign, Activity } from "lucide-react"
import { useFundFlow, useIntradayFundFlow, useFundFlowDetail } from "@/hooks/useFundFlow"
import type { FundFlowItem } from "@/hooks/useFundFlow"
import { selectFundFlowIntraday, selectFundFlowDetail } from "@/hooks/useRealtimeSnapshot"
import type { RealtimeSnapshot } from "@/types/stock"
import { cn, formatLargeNumber } from "@/lib/utils"

interface FundFlowCardProps {
  symbol: string
  snapshot?: RealtimeSnapshot
}

function FlowBar({ value, label }: { value: number | null; label: string }) {
  if (value == null) return null
  const isPositive = value > 0
  const absVal = Math.abs(value)

  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-muted-foreground w-14 shrink-0">{label}</span>
      <div className="flex-1 mx-2 h-3 bg-muted rounded-full overflow-hidden relative">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            isPositive ? "bg-market-up" : "bg-market-down",
          )}
          style={{ width: `${Math.min(absVal / 1e8 * 10, 100)}%` }}
        />
      </div>
      <span className={cn("font-numeric w-20 text-right shrink-0", isPositive ? "text-market-up" : "text-market-down")}>
        {isPositive ? "+" : ""}{formatLargeNumber(value)}
      </span>
    </div>
  )
}

/** Bidirectional bar for inflow/outflow with net amount */
function BiFlowBar({
  label,
  inflow,
  outflow,
  net,
}: {
  label: string
  inflow: number | null
  outflow: number | null
  net: number | null
}) {
  const absIn = Math.abs(inflow ?? 0)
  const absOut = Math.abs(outflow ?? 0)
  const maxVal = Math.max(absIn, absOut, 1)
  // Scale bar widths to 50% max each side
  const inPct = Math.min((absIn / maxVal) * 50, 50)
  const outPct = Math.min((absOut / maxVal) * 50, 50)
  const netVal = net ?? (inflow ?? 0) - Math.abs(outflow ?? 0)
  const isNetPositive = netVal > 0

  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between text-[11px]">
        <span className="text-muted-foreground w-14 shrink-0">{label}</span>
        <span className={cn("font-numeric text-right", isNetPositive ? "text-market-up" : "text-market-down")}>
          净{isNetPositive ? "+" : ""}{formatLargeNumber(netVal)}
        </span>
      </div>
      <div className="flex items-center h-3 gap-0">
        {/* Inflow (red, grows right from center) */}
        <div className="flex-1 flex justify-end">
          <div
            className="h-full rounded-l bg-market-up/70"
            style={{ width: `${inPct}%` }}
          />
        </div>
        {/* Center divider */}
        <div className="w-px h-full bg-border shrink-0" />
        {/* Outflow (green, grows left from center) */}
        <div className="flex-1">
          <div
            className="h-full rounded-r bg-market-down/70"
            style={{ width: `${outPct}%` }}
          />
        </div>
      </div>
      <div className="flex items-center justify-between text-[10px] text-muted-foreground">
        <span className="text-market-up/70 font-numeric">{formatLargeNumber(absIn)}</span>
        <span className="text-market-down/70 font-numeric">{formatLargeNumber(absOut)}</span>
      </div>
    </div>
  )
}

export function FundFlowCard({ symbol, snapshot }: FundFlowCardProps) {
  const { data, isLoading } = useFundFlow(symbol)
  // When snapshot is provided, prefer its data over standalone hooks
  const intradayFallback = useIntradayFundFlow(symbol)
  const detailFallback = useFundFlowDetail(symbol)

  const snapshotFundFlow = selectFundFlowIntraday(snapshot)
  const snapshotDetail = selectFundFlowDetail(snapshot)

  // Build intradayData: use snapshot fund_flow if available, otherwise fallback
  const intradayData: FundFlowItem[] | undefined = snapshotFundFlow
    ? [snapshotFundFlow as FundFlowItem]
    : intradayFallback.data
  const detailData = snapshotDetail
    ? { symbol, inflow: snapshotDetail.inflow, outflow: snapshotDetail.outflow, net: snapshotDetail.net }
    : detailFallback.data

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="py-3">
          <Skeleton className="h-4 w-32" />
        </CardHeader>
        <CardContent className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-4 w-full" />
          ))}
        </CardContent>
      </Card>
    )
  }

  const hasIntraday = intradayData && intradayData.length > 0
  const hasDetail = detailData && detailData.inflow != null
  const hasHistory = data && data.length > 0

  if (!hasIntraday && !hasDetail && !hasHistory) {
    return (
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <DollarSign className="h-4 w-4 text-warning" />
            资金流向
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">暂无资金流向数据</p>
        </CardContent>
      </Card>
    )
  }

  const intraday = hasIntraday ? intradayData[0] : null
  const latest = hasHistory ? data[data.length - 1] : null

  // Detect if we're in trading hours (weekday 9:15-15:05 CST)
  const now = new Date()
  const hours = now.getHours()
  const minutes = now.getMinutes()
  const day = now.getDay()
  const isWeekday = day >= 1 && day <= 5
  const isTradingHours = isWeekday && (
    (hours === 9 && minutes >= 15) ||
    (hours >= 10 && hours < 15) ||
    (hours === 15 && minutes <= 5)
  )

  // Check if intraday and latest history are the same date (fallback duplicate)
  const intradayDate = intraday?.date ?? ""
  const latestDate = latest?.date ?? ""
  const isDuplicate = intradayDate && latestDate && intradayDate === latestDate
    && intraday?.main_net === latest?.main_net

  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <DollarSign className="h-4 w-4 text-warning" />
          资金流向
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Intraday section — skip if data duplicates history (fallback scenario) */}
        {(intraday || hasDetail) && !isDuplicate && (
          <div className="space-y-2">
            <div className="flex items-center gap-1.5">
              <Activity className="h-3 w-3 text-warning" />
              <span className="text-[10px] font-medium text-warning">
                {isTradingHours ? "盘中实时" : "最新数据"}
              </span>
              {!isTradingHours && (
                <Badge variant="secondary" className="text-[9px] px-1 py-0 h-3.5">盘后</Badge>
              )}
              {intraday?.date && (
                <span className="text-[10px] text-muted-foreground ml-auto">{intraday.date}</span>
              )}
            </div>
            {hasDetail ? (
              <>
                {/* Bidirectional legend */}
                <div className="flex items-center justify-between text-[10px] text-muted-foreground px-14">
                  <span className="text-market-up/70">流入</span>
                  <span className="text-market-down/70">流出</span>
                </div>
                <BiFlowBar
                  label="总计"
                  inflow={detailData.inflow ?? null}
                  outflow={detailData.outflow ?? null}
                  net={detailData.net ?? null}
                />
              </>
            ) : null}
            {/* Net flow bars from rank API */}
            {intraday && (
              <>
                <FlowBar value={intraday.main_net} label="主力" />
                <FlowBar value={intraday.super_large_net} label="超大单" />
                <FlowBar value={intraday.large_net} label="大单" />
                <FlowBar value={intraday.medium_net} label="中单" />
                <FlowBar value={intraday.small_net} label="小单" />
              </>
            )}
          </div>
        )}

        {/* Divider between intraday and history */}
        {(intraday || hasDetail) && !isDuplicate && latest && (
          <div className="border-t border-dashed" />
        )}

        {/* When intraday is duplicate, show detail (inflow/outflow) above history */}
        {isDuplicate && hasDetail && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-[10px] text-muted-foreground px-14">
              <span className="text-market-up/70">流入</span>
              <span className="text-market-down/70">流出</span>
            </div>
            <BiFlowBar
              label="总计"
              inflow={detailData.inflow ?? null}
              outflow={detailData.outflow ?? null}
              net={detailData.net ?? null}
            />
            <div className="border-t border-dashed" />
          </div>
        )}

        {/* Historical section — when intraday is duplicate, this becomes the primary display */}
        {latest && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-muted-foreground">
                {isDuplicate ? "最新资金流向" : "近期"}
              </span>
              <span className="text-[10px] text-muted-foreground">{latest.date}</span>
            </div>
            <FlowBar value={latest.main_net} label="主力" />
            <FlowBar value={latest.super_large_net} label="超大单" />
            <FlowBar value={latest.large_net} label="大单" />
            <FlowBar value={latest.medium_net} label="中单" />
            <FlowBar value={latest.small_net} label="小单" />
          </div>
        )}
      </CardContent>
    </Card>
  )
}
