import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Calendar,
  Clock,
  RefreshCw,
  Sun,
  Moon,
  Palmtree,
  TrendingUp,
} from "lucide-react"
import {
  useSchedulerStatus,
  useSchedulePlans,
  useUpdateSchedulePlan,
  useScheduleOverride,
  useSchedulerCalendar,
} from "@/hooks/useScheduler"
import { toast } from "sonner"
import type { SchedulePlan } from "@/types/scheduler"

const PROFILE_CONFIG: Record<string, { label: string; color: string; icon: typeof Sun }> = {
  trading_day: { label: "交易日", color: "bg-info", icon: TrendingUp },
  holiday: { label: "假期模式", color: "bg-warning", icon: Palmtree },
  pre_market: { label: "盘前", color: "bg-accent-primary", icon: Sun },
  after_hours: { label: "盘后", color: "bg-accent-primary", icon: Moon },
}

export function ScheduleManagementTab() {
  const { data: status, isLoading: statusLoading } = useSchedulerStatus()
  const { data: plansData, isLoading: plansLoading } = useSchedulePlans()
  const { data: calendarData } = useSchedulerCalendar(30)
  const updatePlan = useUpdateSchedulePlan()
  const overrideMutation = useScheduleOverride()

  const handleOverride = (value: string) => {
    const profile = value === "auto" ? null : value
    overrideMutation.mutate(profile, {
      onSuccess: () => toast.success(profile ? `已切换至${PROFILE_CONFIG[profile]?.label ?? profile}` : "已恢复自动检测"),
      onError: () => toast.error("切换失败"),
    })
  }

  const handleToggleTask = (planName: string, taskName: string, enabled: boolean) => {
    updatePlan.mutate(
      { plan: planName, tasks: { [taskName]: enabled } },
      {
        onSuccess: () => toast.success("任务配置已更新"),
        onError: () => toast.error("更新失败"),
      },
    )
  }

  return (
    <div className="space-y-6">
      {/* Status Card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <Clock className="h-4 w-4" />
            调度状态
          </CardTitle>
        </CardHeader>
        <CardContent>
          {statusLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-6 w-48" />
              <Skeleton className="h-4 w-64" />
            </div>
          ) : status ? (
            <div className="space-y-4">
              <div className="flex items-center gap-3 flex-wrap">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">当前模式:</span>
                  <ProfileBadge profile={status.current_profile} />
                  {status.override && (
                    <Badge variant="outline" className="text-[10px]">手动覆盖</Badge>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">会话:</span>
                  <Badge variant="secondary" className="text-xs">
                    {status.current_session}
                  </Badge>
                </div>
              </div>

              <div className="flex items-center gap-4 text-sm text-muted-foreground flex-wrap">
                <span>
                  今日{status.is_trading_day ? "是" : "非"}交易日
                </span>
                {status.is_holiday_period && (
                  <Badge variant="destructive" className="text-[10px]">假期中</Badge>
                )}
                <span>下一交易日: {status.next_trading_day}</span>
              </div>

              <div className="flex items-center gap-3">
                <span className="text-sm text-muted-foreground">模式切换:</span>
                <Select
                  value={status.override ?? "auto"}
                  onValueChange={handleOverride}
                >
                  <SelectTrigger className="w-40 h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">自动检测</SelectItem>
                    <SelectItem value="trading_day">交易日</SelectItem>
                    <SelectItem value="holiday">假期模式</SelectItem>
                    <SelectItem value="pre_market">盘前</SelectItem>
                    <SelectItem value="after_hours">盘后</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">无法获取调度状态</p>
          )}
        </CardContent>
      </Card>

      {/* Schedule Plans */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <RefreshCw className="h-4 w-4" />
            调度计划
          </CardTitle>
        </CardHeader>
        <CardContent>
          {plansLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-20 w-full" />
            </div>
          ) : plansData?.plans ? (
            <div className="space-y-4">
              {plansData.plans.map((plan) => (
                <PlanSection
                  key={plan.name}
                  plan={plan}
                  onToggleTask={(taskName, enabled) =>
                    handleToggleTask(plan.name, taskName, enabled)
                  }
                />
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">无计划数据</p>
          )}
        </CardContent>
      </Card>

      {/* Mini Calendar */}
      {calendarData && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Calendar className="h-4 w-4" />
              交易日历 (近 30 天)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <MiniCalendar days={calendarData.days} today={calendarData.today} />
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function ProfileBadge({ profile }: { profile: string }) {
  const cfg = PROFILE_CONFIG[profile]
  if (!cfg) return <Badge variant="secondary">{profile}</Badge>

  const Icon = cfg.icon
  return (
    <Badge className={`${cfg.color} text-white text-xs gap-1`}>
      <Icon className="h-3 w-3" />
      {cfg.label}
    </Badge>
  )
}

function PlanSection({
  plan,
  onToggleTask,
}: {
  plan: SchedulePlan
  onToggleTask: (taskName: string, enabled: boolean) => void
}) {
  return (
    <div className="border rounded-lg p-3 space-y-2">
      <div className="flex items-center gap-2">
        <ProfileBadge profile={plan.name} />
        <span className="text-xs text-muted-foreground">
          默认: {plan.default_enabled ? "全部启用" : "全部禁用"}
        </span>
      </div>
      <div className="space-y-1.5 pl-1">
        {plan.tasks.map((task) => (
          <div key={task.name} className="flex items-center justify-between">
            <span className="text-sm">{task.description || task.name}</span>
            <Switch
              checked={task.enabled}
              onCheckedChange={(checked) => onToggleTask(task.name, checked)}
              className="scale-90"
            />
          </div>
        ))}
      </div>
    </div>
  )
}

function MiniCalendar({ days, today }: { days: { date: string; is_trading_day: boolean; is_weekend: boolean; is_holiday: boolean; day_of_week: number }[]; today: string }) {
  const weekDays = ["一", "二", "三", "四", "五", "六", "日"]

  return (
    <div>
      <div className="grid grid-cols-7 gap-1 mb-1">
        {weekDays.map((d) => (
          <div key={d} className="text-center text-[10px] text-muted-foreground font-medium">
            {d}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {/* Offset for first day alignment */}
        {days.length > 0 &&
          Array.from({ length: days[0].day_of_week }).map((_, i) => (
            <div key={`pad-${i}`} />
          ))}
        {days.map((day) => {
          const isToday = day.date === today
          const bg = day.is_trading_day
            ? "bg-info/15 text-info"
            : day.is_holiday
              ? "bg-warning/15 text-warning"
              : "bg-muted text-muted-foreground"

          return (
            <div
              key={day.date}
              className={`text-center text-[10px] py-1 rounded ${bg} ${isToday ? "ring-1 ring-primary font-bold" : ""}`}
              title={`${day.date}${day.is_trading_day ? " (交易日)" : day.is_holiday ? " (假期)" : " (周末)"}`}
            >
              {parseInt(day.date.slice(-2), 10)}
            </div>
          )
        })}
      </div>
      <div className="flex items-center gap-4 mt-2 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded bg-info/40" /> 交易日
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded bg-warning/40" /> 假期
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded bg-muted" /> 周末
        </span>
      </div>
    </div>
  )
}
