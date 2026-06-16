import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { useWatchlist, useRemoveFromWatchlist } from "@/hooks/useStocks"
import { usePortfolio } from "@/hooks/usePortfolio"
import StockSearch from "@/components/stock/StockSearch"
import { BOARD_LABELS } from "@/lib/constants"
import { Loader2, Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"

export function DataSettingsTab() {
  const { data: stocks, isLoading } = useWatchlist()
  const removeMutation = useRemoveFromWatchlist()
  const { positions } = usePortfolio()
  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [removeTarget, setRemoveTarget] = useState<{ symbol: string; name: string } | null>(null)

  const confirmRemove = () => {
    if (removeTarget) {
      removeMutation.mutate(removeTarget.symbol, {
        onSuccess: () => {
          toast.success(`已移除 ${removeTarget.name}`)
          setRemoveTarget(null)
        },
        onError: () => {
          toast.error("移除失败，请重试")
          setRemoveTarget(null)
        },
      })
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle className="text-sm">自选股列表</CardTitle>
          <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
            <DialogTrigger asChild>
              <Button size="sm" className="gap-1">
                <Plus className="h-4 w-4" />
                添加股票
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>添加股票到自选</DialogTitle>
              </DialogHeader>
              <div className="py-4">
                <StockSearch
                  showAddButton
                  onSelect={() => setAddDialogOpen(false)}
                />
              </div>
            </DialogContent>
          </Dialog>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : stocks && stocks.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>代码</TableHead>
                  <TableHead>名称</TableHead>
                  <TableHead>板块</TableHead>
                  <TableHead className="w-16 text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {stocks.map((s) => (
                  <TableRow key={s.symbol}>
                    <TableCell className="font-mono">{s.symbol}</TableCell>
                    <TableCell className="font-medium">{s.name}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">
                        {BOARD_LABELS[s.board] ?? s.board}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-muted-foreground hover:text-destructive"
                        onClick={() => setRemoveTarget({ symbol: s.symbol, name: s.name })}
                        disabled={removeMutation.isPending}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              暂无自选股
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">配置说明</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            配置文件位于 <code className="text-xs bg-muted px-1 py-0.5 rounded">config/</code> 目录:
          </p>
          <ul className="mt-2 space-y-1 text-sm text-muted-foreground list-disc list-inside">
            <li><code className="text-xs bg-muted px-1 py-0.5 rounded">stocks.yaml</code> -- 自选股列表与数据采集配置</li>
            <li><code className="text-xs bg-muted px-1 py-0.5 rounded">analysis.yaml</code> -- 技术分析参数</li>
            <li><code className="text-xs bg-muted px-1 py-0.5 rounded">web.yaml</code> -- Web 服务配置</li>
          </ul>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={!!removeTarget}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
        title={`移除自选 — ${removeTarget?.name ?? ""}`}
        description={
          positions.some((p) => p.symbol === removeTarget?.symbol)
            ? `确定要从自选列表中移除 ${removeTarget?.name}(${removeTarget?.symbol}) 吗？该股票在您的持仓中，移除自选不会影响持仓记录。`
            : `确定要从自选列表中移除 ${removeTarget?.name}(${removeTarget?.symbol}) 吗？`
        }
        confirmLabel="移除"
        variant="destructive"
        onConfirm={confirmRemove}
        loading={removeMutation.isPending}
      />
    </div>
  )
}
