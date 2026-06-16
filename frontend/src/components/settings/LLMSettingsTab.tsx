import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Loader2 } from "lucide-react"
import { useUsage, useRouting, useBalance, useUpdateRouting, useKeys, useAddKey, useRemoveKey } from "@/hooks/useAdmin"
import { UsageChart } from "@/components/admin/UsageChart"
import { RoutingConfig } from "@/components/admin/RoutingConfig"
import { BalanceCard } from "@/components/admin/BalanceCard"
import { KeyTable } from "@/components/admin/KeyTable"

export function LLMSettingsTab() {
  const { data: usage, isLoading: loadingUsage } = useUsage()
  const { data: routing, isLoading: loadingRouting } = useRouting()
  const { data: balances, isLoading: loadingBalance } = useBalance()
  const updateRouting = useUpdateRouting()
  const { data: keys, isLoading: loadingKeys } = useKeys()
  const addKey = useAddKey()
  const removeKey = useRemoveKey()

  const isLoading = loadingUsage || loadingRouting || loadingBalance || loadingKeys

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* API Keys */}
      <div>
        <h3 className="text-sm font-semibold mb-3">API 密钥管理</h3>
        <KeyTable
          keys={keys ?? []}
          onAdd={(provider, key, label) => addKey.mutate({ provider, key, label })}
          onRemove={(provider, label) => removeKey.mutate({ provider, label })}
        />
      </div>

      {/* Usage stats */}
      {usage && (
        <>
          <h3 className="text-sm font-semibold">使用统计</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <Card>
              <CardHeader className="py-3">
                <CardTitle className="text-xs text-muted-foreground">今日调用</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold tabular-nums">{usage.today?.total_calls ?? 0}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="py-3">
                <CardTitle className="text-xs text-muted-foreground">今日费用</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold font-mono">
                  ${usage.today?.total_cost_usd?.toFixed(4) ?? "0.0000"}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="py-3">
                <CardTitle className="text-xs text-muted-foreground">{usage.period_days}日总费用</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold font-mono">
                  ${usage.total_cost_usd?.toFixed(4) ?? "0.0000"}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="py-3">
                <CardTitle className="text-xs text-muted-foreground">活跃提供商</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold">
                  {usage.providers ? Object.keys(usage.providers).length : 0}
                </p>
              </CardContent>
            </Card>
          </div>
          {usage.providers && <UsageChart providers={usage.providers} />}
        </>
      )}

      {/* Routing + Balance */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {routing && (
          <RoutingConfig
            config={routing}
            onStrategyChange={(strategy) => updateRouting.mutate({ strategy })}
          />
        )}
        {balances && <BalanceCard balances={balances} />}
      </div>
    </div>
  )
}
