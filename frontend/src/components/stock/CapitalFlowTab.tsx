import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Loader2, ArrowUpRight, ArrowDownRight, DollarSign } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import client from "@/api/client"
import { formatLargeNumber } from "@/lib/utils"

interface FundFlowData {
  main_net?: number
  super_large_net?: number
  large_net?: number
  medium_net?: number
  small_net?: number
  date?: string
  [key: string]: number | string | undefined
}

function FlowValue({ value }: { value: number | undefined }) {
  if (value == null) return <span className="text-muted-foreground">—</span>
  const color = value > 0 ? "text-market-up" : value < 0 ? "text-market-down" : "text-muted-foreground"
  const sign = value > 0 ? "+" : ""
  return <span className={`font-mono tabular-nums ${color}`}>{sign}{formatLargeNumber(value)}</span>
}

function FlowBar({ label, value, maxAbs }: { label: string; value: number; maxAbs: number }) {
  const pct = maxAbs > 0 ? Math.abs(value) / maxAbs : 0
  const width = `${Math.max(2, pct * 100)}%`
  const isPositive = value > 0

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-16 text-muted-foreground shrink-0">{label}</span>
      <div className="flex-1 h-4 rounded-sm bg-muted overflow-hidden relative">
        <div
          className={`absolute top-0 h-full rounded-sm transition-all ${isPositive ? "bg-market-up/40 left-1/2" : "bg-market-down/40 right-1/2"}`}
          style={{ width }}
        />
      </div>
      <FlowValue value={value} />
    </div>
  )
}

export function CapitalFlowTab({ symbol }: { symbol: string }) {
  const { data, isLoading, isError } = useQuery<FundFlowData>({
    queryKey: ["stock-fund-flow", symbol],
    queryFn: async () => {
      const { data } = await client.get(`/stock/${symbol}/fund-flow`)
      // The existing API returns a list; take the latest entry
      if (Array.isArray(data) && data.length > 0) {
        return data[data.length - 1] as FundFlowData
      }
      return data as FundFlowData
    },
    staleTime: 120_000,
    refetchInterval: 120_000,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (isError || !data) {
    return (
      <p className="text-xs text-muted-foreground text-center py-8">
        暂无资金流向数据
      </p>
    )
  }

  const mainNet = data.main_net ?? 0
  const huge = data.super_large_net ?? 0
  const large = data.large_net ?? 0
  const medium = data.medium_net ?? 0
  const small = data.small_net ?? 0

  // Generate interpretation based on four-tier structure
  // (main_net and retail_net are always opposite due to zero-sum model, so avoid comparing them)
  const interpretation = (() => {
    const parts: string[] = []
    if (mainNet > 0) {
      if (huge > 0 && large > 0) {
        parts.push("超大单和大单同步流入，机构资金积极买入")
      } else if (huge > 0 && large <= 0) {
        parts.push("超大单主导流入，大单偏弱，大资金独立建仓")
      } else if (huge <= 0 && large > 0) {
        parts.push("大单主导流入，超大单偏弱，中型机构偏积极")
      }
    } else if (mainNet < 0) {
      if (huge < 0 && large < 0) {
        parts.push("超大单和大单同步流出，机构资金集体撤离")
      } else if (huge < 0 && large >= 0) {
        parts.push("超大单主导流出，大单尚在承接，大资金先行离场")
      } else if (huge >= 0 && large < 0) {
        parts.push("大单主导流出，超大单仍在，关注后续走向")
      }
    }

    if (medium > 0 && small > 0) {
      parts.push("中小单同步流入，散户情绪偏多")
    } else if (medium < 0 && small < 0) {
      parts.push("中小单同步流出，散户情绪偏空")
    } else if (medium > 0 && small < 0) {
      parts.push("中单流入但小单流出，散户内部分歧")
    } else if (medium < 0 && small > 0) {
      parts.push("小单流入但中单流出，小散偏积极")
    }

    return parts.join("；") + (parts.length ? "。" : "")
  })()

  const orderTypes = [
    { label: "超大单", value: data.super_large_net ?? 0 },
    { label: "大单", value: data.large_net ?? 0 },
    { label: "中单", value: data.medium_net ?? 0 },
    { label: "小单", value: data.small_net ?? 0 },
  ]
  const maxAbs = Math.max(...orderTypes.map((o) => Math.abs(o.value)), 0.01)

  return (
    <div className="space-y-4">
      {/* Summary */}
      <Card>
        <CardHeader className="py-3 px-4">
          <CardTitle className="text-title flex items-center gap-2">
            <DollarSign className="h-4 w-4 text-accent-primary" />
            资金流向概览
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-[10px] text-muted-foreground">主力净流入（超大单+大单）</p>
              <div className="flex items-center gap-1">
                {mainNet > 0 ? (
                  <ArrowUpRight className="h-4 w-4 text-market-up" />
                ) : mainNet < 0 ? (
                  <ArrowDownRight className="h-4 w-4 text-market-down" />
                ) : null}
                <FlowValue value={mainNet} />
              </div>
            </div>
            <div className="flex gap-4 text-[10px]">
              <span className="text-muted-foreground">超大单 <FlowValue value={huge} /></span>
              <span className="text-muted-foreground">大单 <FlowValue value={large} /></span>
            </div>
          </div>

          {/* Interpretation */}
          {interpretation && (
            <p className="mt-2 text-xs text-muted-foreground leading-relaxed border-l-2 border-accent-primary/40 pl-2">
              {interpretation}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Order type breakdown */}
      <Card>
        <CardHeader className="py-3 px-4">
          <CardTitle className="text-title">订单分类净流入</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3 space-y-2">
          {orderTypes.map((o) => (
            <FlowBar key={o.label} label={o.label} value={o.value} maxAbs={maxAbs} />
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
