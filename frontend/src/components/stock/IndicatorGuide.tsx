import { useState } from "react"
import { ChevronDown, ChevronRight, Lightbulb, TrendingUp, TrendingDown, AlertTriangle } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"

interface IndicatorExplanation {
  name: string
  short_desc: string
  full_desc: string
  params?: Record<string, string>
  signals: Record<string, string>
  beginner_tip: string
}

const INDICATOR_DATA: Record<string, IndicatorExplanation> = {
  MA: {
    name: "移动平均线 (MA)",
    short_desc: "一段时间内的平均收盘价，用于判断趋势方向",
    full_desc: "移动平均线是最基础的技术指标，它计算过去N天的平均收盘价，形成一条平滑的曲线。当股价在均线上方运行，说明当前处于上升趋势；当股价跌破均线，可能意味着趋势转弱。",
    params: {
      "MA_5": "5日均线（短期趋势，反应灵敏但易产生假信号）",
      "MA_10": "10日均线（短中期过渡）",
      "MA_20": "20日均线（中期趋势，月线级别）",
      "MA_60": "60日均线（中长期趋势，季度线，机构常用）",
    },
    signals: {
      "金叉": "短期均线上穿长期均线 → 看涨信号",
      "死叉": "短期均线下穿长期均线 → 看跌信号",
      "均线支撑": "股价回踩均线获得支撑 → 趋势延续",
      "均线跌破": "股价跌破重要均线 → 趋势可能反转",
    },
    beginner_tip: "关注20日和60日均线。股价站上60日线通常意味着中期趋势向好；跌破60日线则需要谨慎。不要仅凭5日线做决定，它波动太大。",
  },
  MACD: {
    name: "MACD 指标",
    short_desc: "趋势跟踪指标，用于判断买卖时机和趋势强弱",
    full_desc: "MACD由两条线和柱状图组成：DIF线（快线）、DEA线（慢线）和MACD柱。简单理解：MACD反映了短期趋势和长期趋势之间的差距。",
    signals: {
      "金叉": "DIF上穿DEA → 买入信号",
      "死叉": "DIF下穿DEA → 卖出信号",
      "零轴上方": "市场处于多头趋势",
      "顶背离": "股价创新高但MACD没创新高 → 注意风险",
      "底背离": "股价创新低但MACD没创新低 → 可能反弹",
    },
    beginner_tip: "MACD最有价值的信号是'背离'。当股价不断上涨但MACD开始走平或下降，说明上涨动力正在减弱，要特别警惕。",
  },
  RSI: {
    name: "相对强弱指标 (RSI)",
    short_desc: "衡量股票超买或超卖程度的动量指标",
    full_desc: "RSI计算一段时间内上涨幅度占总波动幅度的比例，范围在0-100之间。RSI > 70通常认为超买，RSI < 30通常认为超卖。",
    signals: {
      "超买 (>70)": "股价可能回调",
      "超卖 (<30)": "股价可能反弹",
      "50上方运行": "整体偏强",
      "背离": "RSI与股价走势背离 → 趋势可能反转",
    },
    beginner_tip: "RSI超买不等于立刻会跌！强势股的RSI可以长期在70以上运行。超卖区域往往比超买区域更可靠。",
  },
  KDJ: {
    name: "KDJ 随机指标",
    short_desc: "短期超买超卖指标，比RSI更灵敏",
    full_desc: "KDJ由K线、D线和J线三条线组成。J线是最灵敏的一条线，对短期价格变化非常敏感。",
    signals: {
      "金叉": "K线上穿D线 → 短线买入信号",
      "死叉": "K线下穿D线 → 短线卖出信号",
      "J值>100": "极度超买，短期可能回调",
      "J值<0": "极度超卖，短期可能反弹",
    },
    beginner_tip: "KDJ变化非常快，容易产生假信号。建议配合MACD一起使用——当MACD金叉时KDJ也金叉，信号更可靠。",
  },
  BOLL: {
    name: "布林带 (Bollinger Bands)",
    short_desc: "由上中下三条轨道组成，反映价格波动范围",
    full_desc: "布林带由三条线组成：中轨（20日均线）、上轨（中轨+2倍标准差）、下轨（中轨-2倍标准差）。约95%的价格会落在上下轨之间。",
    signals: {
      "触及上轨": "短期偏强，但可能面临压力",
      "触及下轨": "短期偏弱，但可能获得支撑",
      "缩口": "布林带收窄 → 即将出现大幅波动",
      "走带": "股价沿上轨运行 → 强势上涨趋势",
    },
    beginner_tip: "布林带收窄后的突破往往是重要信号。当三条轨道快速收紧，意味着一波大行情即将来临。",
  },
  VOL: {
    name: "成交量",
    short_desc: "交易活跃度的直接体现，量价关系是技术分析的基础",
    full_desc: "成交量是某段时间内的股票交易数量。量价配合是判断趋势的核心依据之一。",
    signals: {
      "放量上涨": "上涨得到资金认可，趋势健康",
      "放量下跌": "抛压沉重，注意风险",
      "缩量上涨": "上涨缺乏资金支持，持续性存疑",
      "缩量下跌": "卖压减轻，可能接近底部",
    },
    beginner_tip: "永远不要忽视成交量！'量在价先'是最重要的规律之一。底部放量通常是资金开始进场的标志。",
  },
}

function SignalBadge({ signal, desc }: { signal: string; desc: string }) {
  const isBullish = desc.includes("买入") || desc.includes("看涨") || desc.includes("反弹") || desc.includes("支撑") || desc.includes("健康") || desc.includes("多头")
  const isBearish = desc.includes("卖出") || desc.includes("看跌") || desc.includes("回调") || desc.includes("风险") || desc.includes("弱")

  return (
    <div className="flex items-start gap-2 py-1">
      {isBullish ? (
        <TrendingUp className="mt-0.5 h-4 w-4 shrink-0 text-market-up" />
      ) : isBearish ? (
        <TrendingDown className="mt-0.5 h-4 w-4 shrink-0 text-market-down" />
      ) : (
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
      )}
      <div>
        <span className="font-medium">{signal}</span>
        <span className="text-muted-foreground ml-1">— {desc}</span>
      </div>
    </div>
  )
}

function IndicatorSection({ id, data }: { id: string; data: IndicatorExplanation }) {
  const [open, setOpen] = useState(false)

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-lg p-3 text-left hover:bg-muted/50 transition-colors">
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        <div className="flex-1">
          <div className="font-medium">{data.name}</div>
          <div className="text-sm text-muted-foreground">{data.short_desc}</div>
        </div>
        <Badge variant="outline" className="text-xs">{id}</Badge>
      </CollapsibleTrigger>
      <CollapsibleContent className="px-3 pb-3">
        <div className="ml-6 space-y-3 border-l-2 border-muted pl-4">
          <p className="text-sm leading-relaxed">{data.full_desc}</p>

          {data.params && (
            <div>
              <h4 className="mb-1 text-sm font-medium">参数说明</h4>
              <div className="space-y-1">
                {Object.entries(data.params).map(([key, desc]) => (
                  <div key={key} className="text-sm">
                    <code className="rounded bg-muted px-1 py-0.5 text-xs">{key}</code>
                    <span className="ml-2 text-muted-foreground">{desc}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div>
            <h4 className="mb-1 text-sm font-medium">信号解读</h4>
            <div className="space-y-0.5">
              {Object.entries(data.signals).map(([signal, desc]) => (
                <SignalBadge key={signal} signal={signal} desc={desc} />
              ))}
            </div>
          </div>

          <div className="rounded-lg bg-warning/5 p-3 text-sm">
            <div className="flex items-start gap-2">
              <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
              <p className="text-warning">{data.beginner_tip}</p>
            </div>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

export default function IndicatorGuide() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <Lightbulb className="h-5 w-5 text-warning" />
          技术指标入门指南
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          点击展开查看每个指标的详细解释和使用建议
        </p>
      </CardHeader>
      <CardContent className="p-0">
        <ScrollArea className="h-[500px]">
          <div className="divide-y px-4">
            {Object.entries(INDICATOR_DATA).map(([id, data]) => (
              <IndicatorSection key={id} id={id} data={data} />
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  )
}
