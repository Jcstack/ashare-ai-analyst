import { useParams, useNavigate, Link } from "react-router-dom"
import { useMemo } from "react"
import {
  ArrowLeft,
  Check,
  X,
  Shield,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Clock,
  Target,
  Loader2,
  Minus,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { useBootstrap, useConfirmAction, useRejectAction } from "@/hooks/useActions"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import type { ActionItem } from "@/types/action"

const actionConfig = {
  buy: { icon: TrendingUp, color: "text-green-500", label: "买入" },
  sell: { icon: TrendingDown, color: "text-red-500", label: "卖出" },
  reduce: { icon: Minus, color: "text-yellow-500", label: "减仓" },
  hold: { icon: Shield, color: "text-blue-500", label: "持有" },
} as const

export default function SignalDetail() {
  const { id = "" } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: bootstrap, isLoading } = useBootstrap()
  const confirmMutation = useConfirmAction()
  const rejectMutation = useRejectAction()

  const item: ActionItem | undefined = useMemo(() => {
    return bootstrap?.action_queue?.find((a) => a.id === id)
  }, [bootstrap, id])

  const handleConfirm = () => {
    confirmMutation.mutate(id, {
      onSuccess: () => {
        toast.success("已确认执行")
        navigate("/")
      },
      onError: () => toast.error("确认失败，请重试"),
    })
  }

  const handleReject = () => {
    rejectMutation.mutate(id, {
      onSuccess: () => {
        toast.success("已暂缓操作")
        navigate("/")
      },
      onError: () => toast.error("操作失败，请重试"),
    })
  }

  if (isLoading) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-40 w-full rounded-lg" />
        <Skeleton className="h-60 w-full rounded-lg" />
      </div>
    )
  }

  if (!item) {
    return (
      <div className="space-y-5">
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to="/">控制塔</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>信号详情</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
        <div className="text-center py-20 text-muted-foreground">
          未找到该操作信号，可能已过期或被处理
        </div>
      </div>
    )
  }

  const cfg = actionConfig[item.action]
  const Icon = cfg.icon
  const plan = item.execution_plan
  const isPending = item.status === "pending"

  return (
    <div className="space-y-5">
      {/* Breadcrumb */}
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to="/">控制塔</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>
              {cfg.label} {item.stock_name}
            </BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Header card */}
      <Card>
        <CardContent className="p-5">
          <div className="flex items-start gap-4">
            <div className={cn("flex h-12 w-12 items-center justify-center rounded-xl", `${cfg.color}/10`)}>
              <Icon className={cn("h-6 w-6", cfg.color)} />
            </div>
            <div className="flex-1 space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-lg font-bold">
                  {cfg.label} {item.stock_name}
                </h1>
                <span className="text-sm text-muted-foreground">{item.symbol}</span>
                <Badge
                  variant={item.status === "pending" ? "default" : "secondary"}
                  className="text-[10px]"
                >
                  {item.status === "pending"
                    ? "待执行"
                    : item.status === "confirmed"
                      ? "已确认"
                      : item.status === "executed"
                        ? "已执行"
                        : item.status === "rejected"
                          ? "已拒绝"
                          : "已过期"}
                </Badge>
              </div>
              <div className="flex items-center gap-3 text-sm text-muted-foreground">
                <span className="font-numeric">
                  置信度 {Math.round(item.confidence * 100)}%
                </span>
                {item.session && <span>{item.session}</span>}
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {new Date(item.created_at).toLocaleString("zh-CN")}
                </span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Execution Plan */}
      <Card>
        <CardHeader className="py-3 px-5">
          <CardTitle className="text-title flex items-center gap-2">
            <Target className="h-4 w-4 text-primary" />
            执行计划
          </CardTitle>
        </CardHeader>
        <CardContent className="px-5 pb-5 space-y-4">
          {/* Thesis summary */}
          <div>
            <h3 className="text-sm font-medium mb-1">投资论点</h3>
            <p className="text-sm text-muted-foreground leading-relaxed">{plan.thesis_summary}</p>
          </div>

          <Separator />

          {/* Key parameters */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="space-y-0.5">
              <span className="text-xs text-muted-foreground">操作窗口</span>
              <p className="text-sm font-medium">{plan.time_window || "--"}</p>
            </div>
            <div className="space-y-0.5">
              <span className="text-xs text-muted-foreground">目标仓位</span>
              <p className="text-sm font-medium font-numeric">
                {plan.target_shares > 0 ? `${plan.target_shares}股` : "--"}
                {plan.target_pct > 0 && ` (${plan.target_pct}%)`}
              </p>
            </div>
            <div className="space-y-0.5">
              <span className="text-xs text-muted-foreground">止损价</span>
              <p className="text-sm font-medium font-numeric text-red-500">
                {plan.stop_loss > 0
                  ? `¥${plan.stop_loss.toFixed(2)} (-${plan.stop_loss_pct.toFixed(1)}%)`
                  : "--"}
              </p>
            </div>
            <div className="space-y-0.5">
              <span className="text-xs text-muted-foreground">目标价</span>
              <p className="text-sm font-medium font-numeric text-green-500">
                {plan.price_target > 0 ? `¥${plan.price_target.toFixed(2)}` : "--"}
              </p>
            </div>
          </div>

          <Separator />

          {/* Price guidance */}
          <div>
            <h3 className="text-sm font-medium mb-1">价格指导</h3>
            <p className="text-sm text-muted-foreground">{plan.price_guidance || "无特别价格指导"}</p>
          </div>
        </CardContent>
      </Card>

      {/* Risk & Contingencies */}
      <Card>
        <CardHeader className="py-3 px-5">
          <CardTitle className="text-title flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-yellow-500" />
            风险与应对
          </CardTitle>
        </CardHeader>
        <CardContent className="px-5 pb-5 space-y-4">
          {/* Key risk */}
          <div>
            <h3 className="text-sm font-medium mb-1">核心风险</h3>
            <p className="text-sm text-muted-foreground">{plan.key_risk || "暂无"}</p>
          </div>

          {/* Invalidation */}
          <div>
            <h3 className="text-sm font-medium mb-1">论点失效条件</h3>
            <p className="text-sm text-red-400">{plan.invalidation || "暂无"}</p>
          </div>

          {/* Contingencies */}
          {plan.contingencies && plan.contingencies.length > 0 && (
            <div>
              <h3 className="text-sm font-medium mb-1">应急预案</h3>
              <ul className="space-y-1">
                {plan.contingencies.map((c, i) => (
                  <li key={i} className="text-sm text-muted-foreground flex items-start gap-1.5">
                    <span className="text-yellow-500 mt-0.5 shrink-0">•</span>
                    {c}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Action buttons (sticky bottom on mobile) */}
      {isPending && (
        <div className="flex items-center gap-3 sticky bottom-4 bg-background/80 backdrop-blur-sm rounded-lg border p-4">
          <Button
            variant="outline"
            className="flex-1 gap-1.5"
            onClick={() => navigate(-1)}
          >
            <ArrowLeft className="h-4 w-4" />
            返回
          </Button>
          <Button
            variant="outline"
            className="flex-1 gap-1.5"
            onClick={handleReject}
            disabled={rejectMutation.isPending}
          >
            {rejectMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <X className="h-4 w-4" />
            )}
            拒绝
          </Button>
          <Button
            className="flex-1 gap-1.5"
            onClick={handleConfirm}
            disabled={confirmMutation.isPending}
          >
            {confirmMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Check className="h-4 w-4" />
            )}
            确认执行
          </Button>
        </div>
      )}
    </div>
  )
}
