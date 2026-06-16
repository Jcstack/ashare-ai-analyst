/** TradeDialog — shared dialog for buy/sell/add/reduce trades.
 *
 * Used by both Portfolio (add/reduce/sell) and Recommendations (buy) pages.
 */

import { useState, useEffect, useMemo } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Loader2 } from "lucide-react"
import { useManualTrade } from "@/hooks/useTrade"

export interface TradeContext {
  action: "buy" | "sell" | "add" | "reduce"
  symbol: string
  stockName: string
  maxShares?: number
  defaultPrice?: number
  recommendationId?: string
}

interface TradeDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  tradeContext: TradeContext | null
}

const ACTION_LABELS: Record<string, string> = {
  buy: "买入",
  sell: "卖出",
  add: "加仓",
  reduce: "减仓",
}

const ACTION_COLORS: Record<string, string> = {
  buy: "bg-market-up/15 text-market-up border-market-up/30",
  add: "bg-market-up/15 text-market-up border-market-up/30",
  sell: "bg-market-down/15 text-market-down border-market-down/30",
  reduce: "bg-market-down/15 text-market-down border-market-down/30",
}

const COMMISSION_RATE = 0.0003
const COMMISSION_MIN = 5
const STAMP_TAX_RATE = 0.001

function calculateFees(action: string, shares: number, price: number) {
  const amount = shares * price
  const commission = Math.max(amount * COMMISSION_RATE, COMMISSION_MIN)
  const stampTax = action === "sell" || action === "reduce" ? amount * STAMP_TAX_RATE : 0
  const total = amount + commission + stampTax
  return { amount, commission, stampTax, total }
}

export function TradeDialog({ open, onOpenChange, tradeContext }: TradeDialogProps) {
  const [shares, setShares] = useState("")
  const [price, setPrice] = useState("")
  const [reasoning, setReasoning] = useState("")
  const manualTrade = useManualTrade()

  // Reset form when context changes
  useEffect(() => {
    if (open && tradeContext) {
      // For sell: lock shares to maxShares; for reduce: start empty
      if (tradeContext.action === "sell" && tradeContext.maxShares) {
        setShares(String(tradeContext.maxShares))
      } else {
        setShares("")
      }
      setPrice(tradeContext.defaultPrice ? String(tradeContext.defaultPrice) : "")
      setReasoning("")
    }
  }, [open, tradeContext])

  const sharesNum = parseInt(shares, 10) || 0
  const priceNum = parseFloat(price) || 0

  const fees = useMemo(
    () => calculateFees(tradeContext?.action ?? "buy", sharesNum, priceNum),
    [tradeContext?.action, sharesNum, priceNum],
  )

  const isSellSide = tradeContext?.action === "sell" || tradeContext?.action === "reduce"
  const maxShares = tradeContext?.maxShares

  const isValid =
    sharesNum > 0 &&
    sharesNum % 100 === 0 &&
    priceNum > 0 &&
    (!isSellSide || !maxShares || sharesNum <= maxShares)

  const handleSubmit = async () => {
    if (!tradeContext || !isValid) return
    await manualTrade.mutateAsync({
      symbol: tradeContext.symbol,
      stock_name: tradeContext.stockName,
      action: tradeContext.action,
      shares: sharesNum,
      price: priceNum,
      reasoning: reasoning || undefined,
      recommendation_id: tradeContext.recommendationId,
    })
    onOpenChange(false)
  }

  if (!tradeContext) return null

  const actionLabel = ACTION_LABELS[tradeContext.action] ?? tradeContext.action

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Badge
              variant="outline"
              className={ACTION_COLORS[tradeContext.action]}
            >
              {actionLabel}
            </Badge>
            {tradeContext.stockName}
            <span className="text-sm text-muted-foreground font-normal font-mono">
              {tradeContext.symbol}
            </span>
          </DialogTitle>
          <DialogDescription>
            {actionLabel} {tradeContext.stockName}（{tradeContext.symbol}）
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Shares */}
          <div className="space-y-2">
            <Label>
              数量（股）
              {isSellSide && maxShares != null && (
                <span className="text-xs text-muted-foreground ml-2">
                  持仓 {maxShares} 股
                </span>
              )}
            </Label>
            <Input
              type="number"
              step={100}
              min={100}
              max={isSellSide && maxShares ? maxShares : undefined}
              placeholder="100"
              value={shares}
              onChange={(e) => setShares(e.target.value)}
              disabled={tradeContext.action === "sell"}
            />
            {shares && sharesNum % 100 !== 0 && (
              <p className="text-xs text-destructive">A股交易以100股（1手）为单位</p>
            )}
            {isSellSide && maxShares != null && sharesNum > maxShares && (
              <p className="text-xs text-destructive">
                不能超过持仓数量 {maxShares} 股
              </p>
            )}
          </div>

          {/* Price */}
          <div className="space-y-2">
            <Label>价格（元）</Label>
            <Input
              type="number"
              step={0.01}
              min={0.01}
              placeholder="10.00"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
            />
          </div>

          {/* Reasoning */}
          <div className="space-y-2">
            <Label>备注（可选）</Label>
            <Textarea
              placeholder="交易理由或备注..."
              value={reasoning}
              onChange={(e) => setReasoning(e.target.value)}
              rows={2}
            />
          </div>

          {/* Fee estimation */}
          {sharesNum > 0 && priceNum > 0 && (
            <div className="rounded-lg border p-3 space-y-1.5 text-xs">
              <div className="flex justify-between">
                <span className="text-muted-foreground">交易金额</span>
                <span className="font-numeric">
                  ¥{fees.amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">佣金（0.03% min ¥5）</span>
                <span className="font-numeric">
                  ¥{fees.commission.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
              </div>
              {fees.stampTax > 0 && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">印花税（卖出 0.1%）</span>
                  <span className="font-numeric">
                    ¥{fees.stampTax.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </span>
                </div>
              )}
              <div className="flex justify-between border-t pt-1.5 font-medium">
                <span>预估总计</span>
                <span className="font-numeric">
                  ¥{fees.total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={!isValid || manualTrade.isPending}
          >
            {manualTrade.isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                处理中...
              </>
            ) : (
              `确认${actionLabel}`
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
