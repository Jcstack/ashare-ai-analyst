import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { HelpCircle } from "lucide-react"
import { useIndicatorExplanations } from "@/hooks/useStocks"
import type { IndicatorsSummary } from "@/types/stock"

interface IndicatorsTableProps {
  indicators: IndicatorsSummary
}

const INDICATOR_GROUPS: Record<string, { keys: string[]; explanationKey: string }> = {
  "均线 MA": { keys: ["MA_5", "MA_10", "MA_20", "MA_60"], explanationKey: "MA" },
  "EMA": { keys: ["EMA_12", "EMA_26"], explanationKey: "MA" },
  "MACD": { keys: ["MACD", "MACD_signal", "MACD_hist"], explanationKey: "MACD" },
  "RSI": { keys: ["RSI"], explanationKey: "RSI" },
  "KDJ": { keys: ["KDJ_K", "KDJ_D", "KDJ_J"], explanationKey: "KDJ" },
  "布林带": { keys: ["BB_upper", "BB_middle", "BB_lower"], explanationKey: "BOLL" },
}

export function IndicatorsTable({ indicators }: IndicatorsTableProps) {
  const values = indicators.values
  const { data: explanations } = useIndicatorExplanations()

  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm">技术指标</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <TooltipProvider>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-32">指标</TableHead>
                <TableHead className="text-right">数值</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {Object.entries(INDICATOR_GROUPS).map(([group, { keys, explanationKey }]) => {
                const available = keys.filter((k) => k in values)
                if (available.length === 0) return null
                const explanation = explanations?.[explanationKey]
                return available.map((key, idx) => (
                  <TableRow key={key}>
                    <TableCell className="font-medium text-sm">
                      {idx === 0 && (
                        <span className="inline-flex items-center gap-1">
                          <span className="text-xs font-semibold text-muted-foreground">{group}</span>
                          {explanation && (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <HelpCircle className="h-3 w-3 text-muted-foreground cursor-help shrink-0" />
                              </TooltipTrigger>
                              <TooltipContent side="right" className="max-w-xs text-left space-y-1.5 p-3">
                                <p className="font-medium text-xs">{explanation.name}</p>
                                <p className="text-xs opacity-90">{explanation.short_desc}</p>
                                <p className="text-xs opacity-75 border-t border-white/20 pt-1.5">{explanation.beginner_tip}</p>
                              </TooltipContent>
                            </Tooltip>
                          )}
                        </span>
                      )}
                      {idx === 0 ? ` ${key}` : key}
                    </TableCell>
                    <TableCell className="col-numeric text-sm">
                      <span className={
                        key === "RSI" && values[key] != null
                          ? values[key]! > 70 ? "text-market-up" : values[key]! < 30 ? "text-market-down" : ""
                          : key === "KDJ_J" && values[key] != null
                            ? values[key]! > 100 ? "text-market-up" : values[key]! < 0 ? "text-market-down" : ""
                            : ""
                      }>
                        {values[key] != null ? values[key]!.toFixed(2) : "--"}
                      </span>
                    </TableCell>
                  </TableRow>
                ))
              })}
            </TableBody>
          </Table>
        </TooltipProvider>
      </CardContent>
    </Card>
  )
}
