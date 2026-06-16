/** Trade decision rich card — buy/sell recommendation with accept/reject.
 *  Accepting a trade calls the backend API to execute + update portfolio. */

import { useState } from "react"
import {
  ShoppingCart, TrendingDown, TrendingUp, Minus,
  AlertTriangle, Check, X, Shield, Loader2,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { cn } from "@/lib/utils"
import { formatPrice } from "@/lib/formatters"
import { usePortfolio, detectBoard } from "@/hooks/usePortfolio"
import {
  executeTrade, acceptRecommendation, rejectRecommendation,
  createGate, confirmGate,
} from "@/api/trade"
import { toast } from "sonner"

// ---- types for optional quantitative data ----

interface KeyMetric {
  label: string
  value: string
  signal?: "bullish" | "bearish" | "neutral"
}

interface DimensionData {
  label: string
  signal: string
  score: number
}

const SIGNAL_STYLE: Record<string, { color: string; label: string; Icon: React.ElementType }> = {
  bullish: { color: "text-market-up", label: "偏多", Icon: TrendingUp },
  bearish: { color: "text-market-down", label: "偏空", Icon: TrendingDown },
  neutral: { color: "text-muted-foreground", label: "中性", Icon: Minus },
}

const REJECT_REASONS = [
  "风险太大",
  "价格不合适",
  "仓位已满",
  "不看好后市",
]

// ---- component ----

interface TradeDecisionProps {
  props: Record<string, unknown>
}

export function TradeDecisionCard({ props }: TradeDecisionProps) {
  const { positions, addPosition, updatePosition, removePosition } = usePortfolio()
  const [executing, setExecuting] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [rejectReason, setRejectReason] = useState("")
  const [decision, setDecision] = useState<"pending" | "accepted" | "rejected">("pending")
  const [rejectedReason, setRejectedReason] = useState("")
  // Gate flow state
  const [gateId, setGateId] = useState<string | null>(null)
  const [gateStage, setGateStage] = useState<
    "idle" | "creating" | "risk_checking" | "risk_approved" | "confirming" | "executing"
  >("idle")

  // ---- parse props ----
  const symbol = typeof props.symbol === "string" ? props.symbol : undefined
  const stockName = typeof props.stock_name === "string" ? props.stock_name : undefined
  const action = typeof props.action === "string" ? props.action : "buy"
  const shares = typeof props.shares === "number" && props.shares > 0 ? props.shares : undefined
  const price = typeof props.price === "number" && props.price > 0 ? props.price : undefined
  const reasoning = typeof props.reasoning === "string" ? props.reasoning : undefined
  const risks = Array.isArray(props.risks) ? (props.risks as string[]) : undefined
  const stopLoss = typeof props.stop_loss === "number" ? props.stop_loss : undefined
  const recommendationId = typeof props.recommendation_id === "string" ? props.recommendation_id : undefined
  const confidence = typeof props.confidence === "number" ? props.confidence : undefined
  const keyMetrics = Array.isArray(props.key_metrics) ? (props.key_metrics as KeyMetric[]) : undefined
  const dimensions = Array.isArray(props.dimensions) ? (props.dimensions as DimensionData[]) : undefined

  const isBuy = action === "buy" || action === "add"
  const actionLabel = isBuy ? "买入" : "卖出"
  const displayName = stockName ?? symbol ?? "未知"

  // ---- handlers ----

  /** Step 1: Create gate + auto risk check. */
  const handleCreateGate = async () => {
    if (!symbol || !shares || !price) return
    setExecuting(true)
    setGateStage("creating")
    try {
      const gate = await createGate({
        trade_type: action as "buy" | "sell" | "add" | "reduce",
        symbol,
        quantity: shares,
        price,
        auto_risk_check: true,
      })
      setGateId(gate.request_id)
      // auto_risk_check=true means server already advanced to risk_approved if OK
      setGateStage(
        gate.current_stage === "risk_approved" ? "risk_approved" : "risk_checking",
      )
    } catch {
      toast.error("风控检查请求失败")
      setGateStage("idle")
      setExecuting(false)
    }
  }

  /** Step 2: Confirm gate + execute trade. */
  const handleAccept = async () => {
    if (!symbol || !shares || !price || !gateId) return
    setGateStage("confirming")
    try {
      await confirmGate(gateId)
      setGateStage("executing")
      await executeTrade({
        symbol,
        stock_name: stockName ?? symbol,
        action: action as "buy" | "sell" | "add" | "reduce",
        shares,
        price,
        reasoning: reasoning ?? "",
        recommendation_id: recommendationId,
      })
      if (recommendationId) {
        await acceptRecommendation(recommendationId)
      }
    } catch {
      toast.error("交易执行失败，请稍后重试")
      setGateStage("idle")
      setGateId(null)
      setExecuting(false)
      return
    }
    setExecuting(false)

    // Sync to local portfolio
    const existing = positions.find((p) => p.symbol === symbol)
    if (isBuy) {
      if (existing) {
        const totalShares = existing.shares + shares
        const newCost =
          (existing.costPrice * existing.shares + price * shares) / totalShares
        updatePosition(existing.id, {
          shares: totalShares,
          costPrice: Math.round(newCost * 100) / 100,
        })
        toast.success(`已加仓 ${displayName} ${shares}股，持仓已更新`)
      } else {
        addPosition({
          symbol,
          name: displayName,
          board: detectBoard(symbol),
          costPrice: price,
          shares,
          buyDate: new Date().toISOString().slice(0, 10),
        })
        toast.success(`已建仓 ${displayName} ${shares}股`)
      }
    } else {
      if (existing) {
        if (shares >= existing.shares) {
          removePosition(existing.id)
          toast.success(`已清仓 ${displayName}`)
        } else {
          updatePosition(existing.id, { shares: existing.shares - shares })
          toast.success(`已减仓 ${displayName} ${shares}股`)
        }
      } else {
        toast.info(`${displayName} 不在持仓中，已记录建议`)
      }
    }

    setDecision("accepted")
    setConfirmOpen(false)
    setGateStage("idle")
    setGateId(null)
  }

  const handleRejectConfirm = async () => {
    const reason = rejectReason.trim()
    if (recommendationId) {
      try {
        await rejectRecommendation(recommendationId)
      } catch {
        // Non-critical
      }
    }
    setRejectedReason(reason || "未说明原因")
    setDecision("rejected")
    setRejectOpen(false)
    toast.info(`已拒绝${actionLabel}建议`)
  }

  // ---- render ----

  return (
    <div className="rounded-md border bg-bg-surface p-4 space-y-3">
      {/* ===== Header ===== */}
      <div className="flex items-center gap-2">
        {isBuy ? (
          <ShoppingCart className="h-4 w-4 text-market-up" />
        ) : (
          <TrendingDown className="h-4 w-4 text-market-down" />
        )}
        <span className="font-semibold text-sm">
          建议{actionLabel} {displayName}
          {symbol && stockName && (
            <span className="text-muted-foreground ml-1">({symbol})</span>
          )}
        </span>
        {decision === "accepted" && (
          <Badge variant="up" className="ml-auto text-[10px]">
            <Check className="h-3 w-3 mr-0.5" />已接受
          </Badge>
        )}
        {decision === "rejected" && (
          <Badge variant="secondary" className="ml-auto text-[10px]">
            <X className="h-3 w-3 mr-0.5" />已拒绝
          </Badge>
        )}
      </div>

      {/* ===== Confidence bar ===== */}
      {confidence != null && confidence > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">置信度</span>
          <div className="w-24 h-1.5 bg-muted rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all",
                confidence >= 0.7
                  ? "bg-market-up"
                  : confidence >= 0.4
                    ? "bg-warning"
                    : "bg-muted-foreground",
              )}
              style={{ width: `${confidence * 100}%` }}
            />
          </div>
          <span className="text-xs font-numeric font-semibold">
            {(confidence * 100).toFixed(0)}%
          </span>
        </div>
      )}

      {/* ===== Trade details ===== */}
      <div className="grid grid-cols-2 gap-2 text-sm">
        {shares && (
          <div>
            <span className="text-muted-foreground">数量</span>
            <span className="ml-2 font-numeric">{shares}股</span>
          </div>
        )}
        {price && (
          <div>
            <span className="text-muted-foreground">价格</span>
            <span className="ml-2 font-numeric">{formatPrice(price)}</span>
          </div>
        )}
      </div>

      {/* ===== Key metrics (quantitative highlights) ===== */}
      {keyMetrics && keyMetrics.length > 0 && (
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs border-t border-border-subtle pt-2.5">
          {keyMetrics.map((m, i) => {
            const s = SIGNAL_STYLE[m.signal ?? "neutral"] ?? SIGNAL_STYLE.neutral
            return (
              <div key={i} className="flex items-center justify-between gap-1">
                <span className="text-muted-foreground truncate">{m.label}</span>
                <span className={cn("font-numeric font-medium shrink-0", s.color)}>
                  {m.value}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* ===== Dimension analysis bars ===== */}
      {dimensions && dimensions.length > 0 && (
        <div className="space-y-1.5 border-t border-border-subtle pt-2.5">
          <span className="text-[10px] text-text-tertiary uppercase tracking-wider">分析维度</span>
          {dimensions.map((dim, i) => {
            const s = SIGNAL_STYLE[dim.signal] ?? SIGNAL_STYLE.neutral
            const pct = Math.round(dim.score * 100)
            return (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="w-14 text-muted-foreground shrink-0 truncate">{dim.label}</span>
                <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full",
                      dim.signal === "bullish"
                        ? "bg-market-up"
                        : dim.signal === "bearish"
                          ? "bg-market-down"
                          : "bg-muted-foreground",
                    )}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className={cn("w-8 text-right font-numeric", s.color)}>
                  {s.label}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* ===== Reasoning ===== */}
      {reasoning && (
        <p className="text-sm text-muted-foreground">{reasoning}</p>
      )}

      {/* ===== Stop loss ===== */}
      {stopLoss && (
        <div className="text-xs text-warning">
          如果跌到 {formatPrice(stopLoss)} 元建议卖出
        </div>
      )}

      {/* ===== Risk warnings ===== */}
      {risks && risks.length > 0 && (
        <div className="flex items-start gap-1.5 text-xs text-warning border-l-2 border-warning pl-2">
          <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />
          <span>{risks.join("; ")}</span>
        </div>
      )}

      {/* ===== Action buttons — only when pending ===== */}
      {decision === "pending" && (
        <div className="flex gap-2 pt-1">
          <Button
            size="sm"
            variant={isBuy ? "default" : "destructive"}
            onClick={() => setConfirmOpen(true)}
            disabled={executing}
          >
            {executing ? "执行中..." : "接受建议"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setRejectOpen(true)}
            disabled={executing}
          >
            拒绝并说明原因
          </Button>
        </div>
      )}

      {/* ===== Post-decision status ===== */}
      {decision === "accepted" && shares && price && (
        <p className="text-xs text-text-secondary">
          已{actionLabel} {displayName} {shares}股，成交价 {formatPrice(price)}
        </p>
      )}
      {decision === "rejected" && rejectedReason && (
        <p className="text-xs text-text-secondary">
          拒绝原因：{rejectedReason}
        </p>
      )}

      {/* ===== Disclaimer ===== */}
      <p className="text-[11px] text-muted-foreground">
        以上建议仅供参考，不构成投资建议。
      </p>

      {/* ===== Accept Confirmation AlertDialog (Gate Flow) ===== */}
      <AlertDialog open={confirmOpen} onOpenChange={(open) => {
        if (!open && gateStage !== "confirming" && gateStage !== "executing") {
          setConfirmOpen(false)
          setGateStage("idle")
          setGateId(null)
          setExecuting(false)
        }
      }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认{actionLabel}</AlertDialogTitle>
            <AlertDialogDescription>
              {actionLabel} {displayName} {shares ? `${shares}股` : ""}
              {price ? `，价格 ${formatPrice(price)}` : ""}
            </AlertDialogDescription>
          </AlertDialogHeader>

          {/* Gate stage progress */}
          <GateStageIndicator stage={gateStage} />

          <AlertDialogFooter>
            <AlertDialogCancel disabled={gateStage === "confirming" || gateStage === "executing"}>
              取消
            </AlertDialogCancel>
            {gateStage === "idle" && (
              <Button onClick={handleCreateGate}>
                <Shield className="h-4 w-4 mr-1" />
                风控检查
              </Button>
            )}
            {(gateStage === "creating" || gateStage === "risk_checking") && (
              <Button disabled>
                <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                检查中…
              </Button>
            )}
            {gateStage === "risk_approved" && (
              <Button onClick={handleAccept}>
                确认{actionLabel}
              </Button>
            )}
            {(gateStage === "confirming" || gateStage === "executing") && (
              <Button disabled>
                <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                执行中…
              </Button>
            )}
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* ===== Reject Reason AlertDialog ===== */}
      <AlertDialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>拒绝原因</AlertDialogTitle>
            <AlertDialogDescription>
              请选择或输入拒绝 {displayName} {actionLabel}建议的原因：
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-3 py-2">
            {/* Preset reason chips */}
            <div className="flex flex-wrap gap-2">
              {REJECT_REASONS.map((r) => (
                <button
                  key={r}
                  className={cn(
                    "rounded-md border px-3 py-1.5 text-xs transition-colors",
                    rejectReason === r
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border-default bg-bg-surface text-text-secondary hover:bg-bg-hover",
                  )}
                  onClick={() => setRejectReason(r)}
                >
                  {r}
                </button>
              ))}
            </div>
            {/* Custom reason textarea */}
            <textarea
              className="w-full rounded-md border border-border-default bg-bg-surface px-3 py-2 text-sm text-text-primary placeholder:text-text-disabled outline-none focus:border-primary transition-colors resize-none"
              rows={2}
              placeholder="或输入自定义原因..."
              value={REJECT_REASONS.includes(rejectReason) ? "" : rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <Button variant="outline" onClick={handleRejectConfirm}>
              确认拒绝
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

// ---- Gate stage progress indicator ----

const GATE_STEPS = [
  { key: "risk", label: "风控检查" },
  { key: "confirm", label: "用户确认" },
  { key: "execute", label: "执行交易" },
] as const

function stageToStep(
  stage: "idle" | "creating" | "risk_checking" | "risk_approved" | "confirming" | "executing",
): number {
  switch (stage) {
    case "idle":
      return -1
    case "creating":
    case "risk_checking":
      return 0
    case "risk_approved":
      return 1
    case "confirming":
      return 1
    case "executing":
      return 2
  }
}

function GateStageIndicator({
  stage,
}: {
  stage: "idle" | "creating" | "risk_checking" | "risk_approved" | "confirming" | "executing"
}) {
  if (stage === "idle") return null
  const current = stageToStep(stage)
  const isComplete = (i: number) =>
    i < current || (i === current && (stage === "risk_approved" || stage === "executing"))
  const isActive = (i: number) =>
    i === current && !isComplete(i)

  return (
    <div className="flex items-center gap-1 py-2">
      {GATE_STEPS.map((step, i) => (
        <div key={step.key} className="flex items-center gap-1 flex-1">
          <div
            className={cn(
              "h-5 w-5 rounded-full flex items-center justify-center text-[10px] font-medium shrink-0",
              isComplete(i)
                ? "bg-market-up text-white"
                : isActive(i)
                  ? "bg-primary text-white"
                  : "bg-muted text-muted-foreground",
            )}
          >
            {isComplete(i) ? (
              <Check className="h-3 w-3" />
            ) : isActive(i) ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              i + 1
            )}
          </div>
          <span
            className={cn(
              "text-[11px] truncate",
              isComplete(i) || isActive(i) ? "text-text-primary" : "text-muted-foreground",
            )}
          >
            {step.label}
          </span>
          {i < GATE_STEPS.length - 1 && (
            <div
              className={cn(
                "flex-1 h-px mx-1",
                isComplete(i) ? "bg-market-up" : "bg-muted",
              )}
            />
          )}
        </div>
      ))}
    </div>
  )
}
