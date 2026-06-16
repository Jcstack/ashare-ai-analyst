import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { RoutingConfig as RoutingConfigType } from "@/types/admin"

interface RoutingConfigProps {
  config: RoutingConfigType
  onStrategyChange: (strategy: string) => void
}

export function RoutingConfig({ config, onStrategyChange }: RoutingConfigProps) {
  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm">路由配置</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <p className="text-xs text-muted-foreground mb-2">可用提供商</p>
          <div className="flex flex-wrap gap-2">
            {config.available_providers.map((p) => (
              <Badge key={p} variant="secondary">{p}</Badge>
            ))}
            {config.available_providers.length === 0 && (
              <span className="text-sm text-muted-foreground">无可用提供商</span>
            )}
          </div>
        </div>
        <div>
          <p className="text-xs text-muted-foreground mb-2">路由策略</p>
          <Select onValueChange={onStrategyChange}>
            <SelectTrigger className="w-48">
              <SelectValue placeholder="选择策略" />
            </SelectTrigger>
            <SelectContent>
              {config.strategies.map((s) => (
                <SelectItem key={s} value={s}>{s}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardContent>
    </Card>
  )
}
