import { useMemo } from "react"
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Bar,
  Area,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ReferenceArea,
} from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { TrendingUp, TrendingDown, Minus } from "lucide-react"
import type { IndicatorsFullRecord } from "@/types/stock"

interface IndicatorsChartProps {
  data: IndicatorsFullRecord[]
}

/** Detect MACD golden/death cross points */
function detectMACDCrosses(
  chartData: Array<{ date: string; MACD?: number; MACD_signal?: number }>,
): Array<{ date: string; crossValue: number; type: "golden" | "death" }> {
  const crosses: Array<{ date: string; crossValue: number; type: "golden" | "death" }> = []
  for (let i = 1; i < chartData.length; i++) {
    const prev = chartData[i - 1]
    const curr = chartData[i]
    if (prev.MACD == null || prev.MACD_signal == null || curr.MACD == null || curr.MACD_signal == null) continue
    const prevDiff = prev.MACD - prev.MACD_signal
    const currDiff = curr.MACD - curr.MACD_signal
    if (prevDiff <= 0 && currDiff > 0) {
      crosses.push({ date: curr.date, crossValue: curr.MACD, type: "golden" })
    } else if (prevDiff >= 0 && currDiff < 0) {
      crosses.push({ date: curr.date, crossValue: curr.MACD, type: "death" })
    }
  }
  return crosses
}

function TrendIcon({ current, previous }: { current: number | undefined; previous: number | undefined }) {
  if (current == null || previous == null) return <Minus className="h-3 w-3 text-muted-foreground" />
  if (current > previous) return <TrendingUp className="h-3 w-3 text-market-up" />
  if (current < previous) return <TrendingDown className="h-3 w-3 text-market-down" />
  return <Minus className="h-3 w-3 text-muted-foreground" />
}

export function IndicatorsChart({ data }: IndicatorsChartProps) {
  // Only use last 120 records for readability
  const chartData = useMemo(
    () =>
      data.slice(-120).map((d) => ({
        date: d.date,
        close: d.close,
        MACD: d.indicators.MACD ?? undefined,
        MACD_signal: d.indicators.MACD_signal ?? undefined,
        MACD_hist: d.indicators.MACD_hist ?? undefined,
        RSI: d.indicators.RSI ?? undefined,
        KDJ_K: d.indicators.KDJ_K ?? undefined,
        KDJ_D: d.indicators.KDJ_D ?? undefined,
        KDJ_J: d.indicators.KDJ_J ?? undefined,
        BB_upper: d.indicators.BB_upper ?? undefined,
        BB_middle: d.indicators.BB_middle ?? undefined,
        BB_lower: d.indicators.BB_lower ?? undefined,
        OBV: d.indicators.OBV ?? undefined,
        MA_5: d.indicators.MA_5 ?? undefined,
        MA_10: d.indicators.MA_10 ?? undefined,
        MA_20: d.indicators.MA_20 ?? undefined,
        MA_60: d.indicators.MA_60 ?? undefined,
        EMA_12: d.indicators.EMA_12 ?? undefined,
        EMA_26: d.indicators.EMA_26 ?? undefined,
      })),
    [data],
  )

  // MACD golden/death cross markers
  const macdWithCrosses = useMemo(() => {
    const crosses = detectMACDCrosses(chartData)
    const crossMap = new Map(crosses.map((c) => [c.date, c]))
    return chartData.map((d) => {
      const cross = crossMap.get(d.date)
      return {
        ...d,
        goldenCross: cross?.type === "golden" ? cross.crossValue : undefined,
        deathCross: cross?.type === "death" ? cross.crossValue : undefined,
      }
    })
  }, [chartData])

  // Check which indicators are available
  const hasBB = chartData.some((d) => d.BB_upper != null)
  const hasOBV = chartData.some((d) => d.OBV != null)
  const hasMA = chartData.some((d) => d.MA_5 != null || d.MA_20 != null)

  // Get latest and previous values for MA overview
  const latest = chartData[chartData.length - 1]
  const prev = chartData.length >= 2 ? chartData[chartData.length - 2] : undefined

  return (
    <div className="space-y-4">
      {/* Moving Average Overview Card */}
      {hasMA && (
        <Card>
          <CardHeader className="py-3">
            <CardTitle className="text-sm">均线概览</CardTitle>
          </CardHeader>
          <CardContent className="pb-3">
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
              {[
                { label: "MA5", value: latest?.MA_5, prev: prev?.MA_5, color: "#FF6B6B" },
                { label: "MA10", value: latest?.MA_10, prev: prev?.MA_10, color: "#4ECDC4" },
                { label: "MA20", value: latest?.MA_20, prev: prev?.MA_20, color: "#45B7D1" },
                { label: "MA60", value: latest?.MA_60, prev: prev?.MA_60, color: "#96CEB4" },
                { label: "EMA12", value: latest?.EMA_12, prev: prev?.EMA_12, color: "#FFEAA7" },
                { label: "EMA26", value: latest?.EMA_26, prev: prev?.EMA_26, color: "#DDA0DD" },
              ].map((ma) => (
                <div key={ma.label} className="text-center">
                  <div className="text-[10px] text-muted-foreground mb-0.5 flex items-center justify-center gap-1">
                    <span className="w-2 h-0.5 rounded" style={{ backgroundColor: ma.color }} />
                    {ma.label}
                  </div>
                  <div className="text-xs font-numeric font-medium">
                    {ma.value != null ? ma.value.toFixed(2) : "--"}
                  </div>
                  <div className="flex justify-center mt-0.5">
                    <TrendIcon current={ma.value} previous={ma.prev} />
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* MACD with golden/death cross markers (FR-CA003) */}
      <Card>
        <CardHeader className="py-3">
          <div className="flex items-center gap-3">
            <CardTitle className="text-sm">MACD</CardTitle>
            <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
              <span className="flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full bg-market-up" />
                金叉
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full bg-market-down" />
                死叉
              </span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="pb-3">
          <ResponsiveContainer width="100%" height={150}>
            <ComposedChart data={macdWithCrosses}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.1} />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v: string) => v.slice(5)} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <ReferenceLine y={0} stroke="#666" strokeDasharray="3 3" />
              <Bar dataKey="MACD_hist" fill="#8884d8" opacity={0.5} />
              <Line dataKey="MACD" stroke="#EF5350" dot={false} strokeWidth={1.5} />
              <Line dataKey="MACD_signal" stroke="#26A69A" dot={false} strokeWidth={1.5} />
              <Scatter dataKey="goldenCross" fill="#EF5350" shape="circle" />
              <Scatter dataKey="deathCross" fill="#26A69A" shape="diamond" />
            </ComposedChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      {/* Bollinger Bands */}
      {hasBB && (
        <Card>
          <CardHeader className="py-3">
            <div className="flex items-center gap-3">
              <CardTitle className="text-sm">布林带 (Bollinger Bands)</CardTitle>
              <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                <span className="flex items-center gap-1">
                  <span className="inline-block w-2 h-0.5 bg-info" />
                  上轨/下轨
                </span>
                <span className="flex items-center gap-1">
                  <span className="inline-block w-2 h-0.5 bg-warning" />
                  中轨
                </span>
                <span className="flex items-center gap-1">
                  <span className="inline-block w-2 h-0.5 bg-foreground" />
                  收盘价
                </span>
              </div>
            </div>
          </CardHeader>
          <CardContent className="pb-3">
            <ResponsiveContainer width="100%" height={180}>
              <ComposedChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.1} />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v: string) => v.slice(5)} />
                <YAxis domain={["auto", "auto"]} tick={{ fontSize: 10 }} />
                <Tooltip />
                <Area
                  dataKey="BB_upper"
                  stroke="transparent"
                  fill="#60A5FA"
                  fillOpacity={0.08}
                  connectNulls
                />
                <Area
                  dataKey="BB_lower"
                  stroke="transparent"
                  fill="transparent"
                  connectNulls
                />
                <Line dataKey="BB_upper" stroke="#60A5FA" dot={false} strokeWidth={1} strokeDasharray="3 3" />
                <Line dataKey="BB_lower" stroke="#60A5FA" dot={false} strokeWidth={1} strokeDasharray="3 3" />
                <Line dataKey="BB_middle" stroke="#FB923C" dot={false} strokeWidth={1.5} />
                <Line dataKey="close" stroke="currentColor" dot={false} strokeWidth={1.5} />
              </ComposedChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* RSI with overbought/oversold threshold zones (FR-CA003) */}
      <Card>
        <CardHeader className="py-3">
          <div className="flex items-center gap-3">
            <CardTitle className="text-sm">RSI</CardTitle>
            <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
              <span className="flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded bg-market-up/20 border border-market-up/40" />
                超买 (&gt;70)
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded bg-market-down/20 border border-market-down/40" />
                超卖 (&lt;30)
              </span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="pb-3">
          <ResponsiveContainer width="100%" height={120}>
            <ComposedChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.1} />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v: string) => v.slice(5)} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} />
              <Tooltip />
              {/* Overbought zone: 70-100 (light red) */}
              <ReferenceArea y1={70} y2={100} fill="#EF5350" fillOpacity={0.06} />
              {/* Oversold zone: 0-30 (light green) */}
              <ReferenceArea y1={0} y2={30} fill="#26A69A" fillOpacity={0.06} />
              <ReferenceLine y={70} stroke="#EF5350" strokeDasharray="3 3" />
              <ReferenceLine y={30} stroke="#26A69A" strokeDasharray="3 3" />
              <Line dataKey="RSI" stroke="#AB47BC" dot={false} strokeWidth={1.5} />
            </ComposedChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      {/* KDJ with J-value reference lines (FR-CA003) */}
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm">KDJ</CardTitle>
        </CardHeader>
        <CardContent className="pb-3">
          <ResponsiveContainer width="100%" height={120}>
            <ComposedChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.1} />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v: string) => v.slice(5)} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              {/* J-value extreme reference lines */}
              <ReferenceLine y={0} stroke="#26A69A" strokeDasharray="2 4" strokeOpacity={0.5} />
              <ReferenceLine y={100} stroke="#EF5350" strokeDasharray="2 4" strokeOpacity={0.5} />
              <Line dataKey="KDJ_K" stroke="#FFB74D" dot={false} strokeWidth={1.5} />
              <Line dataKey="KDJ_D" stroke="#4FC3F7" dot={false} strokeWidth={1.5} />
              <Line dataKey="KDJ_J" stroke="#AB47BC" dot={false} strokeWidth={1.5} />
            </ComposedChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      {/* OBV Energy Tide */}
      {hasOBV && (
        <Card>
          <CardHeader className="py-3">
            <CardTitle className="text-sm">OBV 能量潮</CardTitle>
          </CardHeader>
          <CardContent className="pb-3">
            <ResponsiveContainer width="100%" height={120}>
              <ComposedChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.1} />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v: string) => v.slice(5)} />
                <YAxis tick={{ fontSize: 10 }} tickFormatter={(v: number) => {
                  if (Math.abs(v) >= 1e8) return `${(v / 1e8).toFixed(1)}亿`
                  if (Math.abs(v) >= 1e4) return `${(v / 1e4).toFixed(0)}万`
                  return v.toString()
                }} />
                <Tooltip />
                <Area dataKey="OBV" stroke="#42A5F5" fill="#42A5F5" fillOpacity={0.1} dot={false} strokeWidth={1.5} />
              </ComposedChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* Raw Indicators Table */}
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm">指标原始值</CardTitle>
        </CardHeader>
        <CardContent className="pb-3">
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-x-4 gap-y-2 text-xs">
            {latest && Object.entries({
              MACD: latest.MACD,
              MACD_signal: latest.MACD_signal,
              MACD_hist: latest.MACD_hist,
              RSI: latest.RSI,
              KDJ_K: latest.KDJ_K,
              KDJ_D: latest.KDJ_D,
              KDJ_J: latest.KDJ_J,
              BB_upper: latest.BB_upper,
              BB_middle: latest.BB_middle,
              BB_lower: latest.BB_lower,
              OBV: latest.OBV,
              MA_5: latest.MA_5,
              MA_10: latest.MA_10,
              MA_20: latest.MA_20,
              MA_60: latest.MA_60,
              EMA_12: latest.EMA_12,
              EMA_26: latest.EMA_26,
            })
              .filter(([, v]) => v != null)
              .map(([key, value]) => (
                <div key={key} className="flex items-center justify-between">
                  <span className="text-muted-foreground">{key}</span>
                  <span className="font-numeric font-medium">
                    {typeof value === "number"
                      ? Math.abs(value) >= 1e6
                        ? `${(value / 1e8).toFixed(2)}亿`
                        : value.toFixed(2)
                      : "--"}
                  </span>
                </div>
              ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
