import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type { BalanceInfo } from "@/types/admin"

interface BalanceCardProps {
  balances: BalanceInfo[]
}

export function BalanceCard({ balances }: BalanceCardProps) {
  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm">账户余额</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {balances.map((b) => (
            <div key={b.provider} className="flex items-center justify-between">
              <Badge variant="secondary">{b.provider}</Badge>
              <div className="text-right">
                {b.status === "error" ? (
                  <span className="text-sm text-destructive">{b.message}</span>
                ) : (
                  <span className="font-mono text-sm">
                    ${b.balance?.toFixed(2) ?? "--"}
                  </span>
                )}
              </div>
            </div>
          ))}
          {balances.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-4">暂无数据</p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
