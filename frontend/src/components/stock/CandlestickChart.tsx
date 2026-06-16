import { useEffect, useRef } from "react"
import { createChart, createSeriesMarkers, type IChartApi, ColorType, CandlestickSeries, HistogramSeries, LineSeries, AreaSeries, LineStyle } from "lightweight-charts"
import type { OHLCVRecord, IndicatorsFullRecord, SupportResistanceLevel } from "@/types/stock"
import type { ChartEvent } from "@/types/analysis"

/** Marker shape mapping for event types */
const EVENT_MARKER_CONFIG: Record<string, { shape: "circle" | "arrowUp" | "arrowDown" | "square"; color: string; position: "aboveBar" | "belowBar" }> = {
  news: { shape: "circle", color: "#3b82f6", position: "belowBar" },
  dragon_tiger: { shape: "arrowUp", color: "#f97316", position: "belowBar" },
  pattern: { shape: "square", color: "#a855f7", position: "aboveBar" },
  anomaly: { shape: "arrowDown", color: "#eab308", position: "belowBar" },
}

interface CandlestickChartProps {
  data: OHLCVRecord[]
  indicatorsData?: IndicatorsFullRecord[]
  chartEvents?: ChartEvent[]
  srLevels?: SupportResistanceLevel[]
  height?: number
  /** When true, renders an area/line chart instead of candlesticks (for timeline mode) */
  timelineMode?: boolean
}

export function CandlestickChart({ data, indicatorsData, chartEvents, srLevels, height = 620, timelineMode = false }: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#999",
      },
      grid: {
        vertLines: { color: "rgba(197, 203, 206, 0.1)" },
        horzLines: { color: "rgba(197, 203, 206, 0.1)" },
      },
      width: containerRef.current.clientWidth,
      height,
      crosshair: { mode: 0 },
      rightPriceScale: {
        borderColor: "rgba(197, 203, 206, 0.3)",
        scaleMargins: { top: 0.08, bottom: 0.02 },
      },
      timeScale: { borderColor: "rgba(197, 203, 206, 0.3)" },
    })
    chartRef.current = chart

    if (timelineMode) {
      // Timeline / intraday: area chart
      const firstClose = data[0]?.close ?? 0
      const lastClose = data[data.length - 1]?.close ?? 0
      const isUp = lastClose >= firstClose
      const lineColor = isUp ? "#EF5350" : "#26A69A"

      const areaSeries = chart.addSeries(AreaSeries, {
        lineColor,
        topColor: isUp ? "rgba(239, 83, 80, 0.28)" : "rgba(38, 166, 154, 0.28)",
        bottomColor: isUp ? "rgba(239, 83, 80, 0.02)" : "rgba(38, 166, 154, 0.02)",
        lineWidth: 2,
        priceLineVisible: true,
      })

      areaSeries.setData(
        data.map((d) => ({ time: d.date, value: d.close }))
      )

      // Prev close reference line
      if (firstClose > 0) {
        areaSeries.createPriceLine({
          price: firstClose,
          color: "#666",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: "昨收",
        })
      }
    } else {
      // Candlestick series — A-share colors
      const candleSeries = chart.addSeries(CandlestickSeries, {
        upColor: "#EF5350",
        downColor: "#26A69A",
        borderUpColor: "#EF5350",
        borderDownColor: "#26A69A",
        wickUpColor: "#EF5350",
        wickDownColor: "#26A69A",
      })

      candleSeries.setData(
        data.map((d) => ({
          time: d.date,
          open: d.open,
          high: d.high,
          low: d.low,
          close: d.close,
        }))
      )

      // Chart event markers (FR-CA001) — icon only, no text; deduplicated by date
      if (chartEvents && chartEvents.length > 0) {
        const PRIORITY: Record<string, number> = { anomaly: 4, dragon_tiger: 3, news: 2, pattern: 1 }
        const validDates = new Set(data.map((d) => d.date))
        const validEvents = chartEvents.filter((e) => validDates.has(e.date))

        // Group by date: keep highest-priority event per day + count
        const byDate = new Map<string, { event: ChartEvent; count: number }>()
        for (const e of validEvents) {
          const existing = byDate.get(e.date)
          const ePriority = PRIORITY[e.type] ?? 0
          if (!existing || ePriority > (PRIORITY[existing.event.type] ?? 0)) {
            byDate.set(e.date, { event: e, count: (existing?.count ?? 0) + 1 })
          } else {
            existing.count++
          }
        }

        // Take latest 20 dates, build markers without text (or count badge only)
        const sortedDates = [...byDate.entries()]
          .sort((a, b) => a[0].localeCompare(b[0]))
          .slice(-20)

        const markers = sortedDates.map(([date, { event, count }]) => {
          const config = EVENT_MARKER_CONFIG[event.type] ?? EVENT_MARKER_CONFIG.news
          return {
            time: date,
            position: config.position as "aboveBar" | "belowBar",
            color: config.color,
            shape: config.shape as "circle" | "arrowUp" | "arrowDown" | "square",
            text: count > 1 ? String(count) : "",
          }
        })

        if (markers.length > 0) {
          createSeriesMarkers(candleSeries, markers)
        }
      }

      // Support/Resistance price lines (FR-CA002)
      if (srLevels && srLevels.length > 0) {
        for (const level of srLevels) {
          const isSupport = level.type === "support"
          candleSeries.createPriceLine({
            price: level.level,
            color: isSupport ? "#26A69A" : "#EF5350",
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: isSupport ? `支撑 ¥${level.level}` : `阻力 ¥${level.level}`,
          })
        }
      }

      // MA overlays from indicators data
      if (indicatorsData && indicatorsData.length > 0) {
        const maColors: Record<string, string> = {
          MA_5: "#FFB74D",
          MA_10: "#4FC3F7",
          MA_20: "#AB47BC",
          MA_60: "#EF5350",
        }
        const maKeys = ["MA_5", "MA_10", "MA_20", "MA_60"]

        for (const maKey of maKeys) {
          const maData = indicatorsData
            .filter((d) => d.indicators[maKey] != null)
            .map((d) => ({ time: d.date, value: d.indicators[maKey]! }))

          if (maData.length > 0) {
            const lineSeries = chart.addSeries(LineSeries, {
              color: maColors[maKey] ?? "#999",
              lineWidth: 1,
              priceLineVisible: false,
              lastValueVisible: false,
            })
            lineSeries.setData(maData)
          }
        }
      }
    }

    // Volume series (always shown)
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    })

    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.75, bottom: 0 },
    })

    volumeSeries.setData(
      data.map((d, i) => ({
        time: d.date,
        value: d.volume,
        color:
          i > 0 && d.close >= data[i - 1].close
            ? "rgba(239, 83, 80, 0.3)"
            : "rgba(38, 166, 154, 0.3)",
      }))
    )

    chart.timeScale().fitContent()

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth })
      }
    }
    window.addEventListener("resize", handleResize)

    return () => {
      window.removeEventListener("resize", handleResize)
      chart.remove()
      chartRef.current = null
    }
  }, [data, indicatorsData, chartEvents, srLevels, height, timelineMode])

  return <div ref={containerRef} className="w-full" />
}
