import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  Bell,
  MessageSquare,
  Send,
  Globe,
  Webhook,
  ChevronDown,
} from "lucide-react"
import { useSentinelConfig, useUpdateSentinelConfig } from "@/hooks/useScheduler"
import { getNotificationPrefs, updateNotificationPrefs } from "@/api/user-config"
import { toast } from "sonner"
import type { NotificationChannel } from "@/types/scheduler"
import type { NotificationPrefs } from "@/types/intelligence"

const CHANNEL_CONFIG: Record<string, { label: string; icon: typeof Bell; color: string }> = {
  wecom: { label: "企业微信", icon: MessageSquare, color: "text-info" },
  dingtalk: { label: "钉钉", icon: MessageSquare, color: "text-info" },
  telegram: { label: "Telegram", icon: Send, color: "text-accent-primary" },
  webhook: { label: "通用 Webhook", icon: Webhook, color: "text-accent-primary" },
}

const EVENT_LABELS: Record<string, string> = {
  reopen_briefing: "开盘前研判",
  holiday_impact: "假期影响评估",
  risk_alert: "风险预警",
  sentiment_update: "舆情变动",
  advisor_signal: "投顾信号",
  market_overview: "市场概览",
  all: "全部事件",
}

const USER_CHANNELS = [
  { value: "app", label: "应用内" },
  { value: "wecom", label: "企业微信" },
  { value: "dingtalk", label: "钉钉" },
  { value: "telegram", label: "Telegram" },
]

const DIVERSITY_OPTIONS = [
  { value: "low", label: "低", desc: "仅推送高匹配信号" },
  { value: "medium", label: "中", desc: "兼顾匹配与发现" },
  { value: "high", label: "高", desc: "更多随机与跨域信号" },
]

const DEFAULT_PREFS: NotificationPrefs = {
  quiet_hours_start: "22:00",
  quiet_hours_end: "08:00",
  max_daily_notifications: 50,
  digest_interval_minutes: 30,
  enabled_channels: ["app"],
  min_confidence_threshold: 30,
  diversity_level: "medium",
}

export function NotificationSettingsTab() {
  const { data: config, isLoading: sentinelLoading } = useSentinelConfig()
  const updateMutation = useUpdateSentinelConfig()

  // User-level prefs state
  const [prefs, setPrefs] = useState<NotificationPrefs>(DEFAULT_PREFS)
  const [prefsSaving, setPrefsSaving] = useState(false)
  const [prefsSaved, setPrefsSaved] = useState(false)
  const [prefsLoading, setPrefsLoading] = useState(true)

  // Advanced section collapse
  const [advancedOpen, setAdvancedOpen] = useState(false)

  useEffect(() => {
    getNotificationPrefs()
      .then(setPrefs)
      .catch(() => toast.error("加载推送偏好失败"))
      .finally(() => setPrefsLoading(false))
  }, [])

  const channels = config?.notifications?.channels ?? []
  const eventTypes = config?.notifications?.event_types ?? []
  const dataSources = config?.data_sources ?? {}

  const handleToggleChannel = (index: number, enabled: boolean) => {
    if (!config) return
    const updated = [...channels]
    updated[index] = { ...updated[index], enabled }
    updateMutation.mutate(
      { notifications: { ...config.notifications, channels: updated } },
      {
        onSuccess: () => toast.success(enabled ? "推送渠道已启用" : "推送渠道已禁用"),
        onError: () => toast.error("更新失败"),
      },
    )
  }

  const handleToggleEvent = (channelIndex: number, event: string, add: boolean) => {
    if (!config) return
    const updated = [...channels]
    const ch = { ...updated[channelIndex] }
    const events = new Set(ch.events)
    if (add) {
      events.add(event)
    } else {
      events.delete(event)
    }
    ch.events = Array.from(events)
    updated[channelIndex] = ch
    updateMutation.mutate(
      { notifications: { ...config.notifications, channels: updated } },
      {
        onSuccess: () => toast.success("事件订阅已更新"),
        onError: () => toast.error("更新失败"),
      },
    )
  }

  const handleToggleDataSource = (key: string, enabled: boolean) => {
    if (!config) return
    const updated = { ...dataSources }
    if (updated[key as keyof typeof updated]) {
      (updated[key as keyof typeof updated] as { enabled: boolean }).enabled = enabled
    }
    updateMutation.mutate(
      { data_sources: updated },
      {
        onSuccess: () => toast.success("系统数据源配置已更新"),
        onError: () => toast.error("更新失败"),
      },
    )
  }

  const handleSavePrefs = async () => {
    setPrefsSaving(true)
    setPrefsSaved(false)
    try {
      const updated = await updateNotificationPrefs(prefs)
      setPrefs(updated)
      setPrefsSaved(true)
      setTimeout(() => setPrefsSaved(false), 2000)
    } catch {
      toast.error("保存失败，请重试")
    } finally {
      setPrefsSaving(false)
    }
  }

  const toggleUserChannel = (ch: string) => {
    setPrefs((prev) => ({
      ...prev,
      enabled_channels: prev.enabled_channels.includes(ch)
        ? prev.enabled_channels.filter((c) => c !== ch)
        : [...prev.enabled_channels, ch],
    }))
  }

  if (sentinelLoading || prefsLoading) {
    return (
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">通知与推送</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* User-level notification preferences */}

      {/* Quiet hours */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">免打扰时段</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">
            在此时段内，非紧急通知将被暂存为摘要
          </p>
          <div className="flex items-center gap-3">
            <Input
              type="time"
              value={prefs.quiet_hours_start}
              onChange={(e) => setPrefs((p) => ({ ...p, quiet_hours_start: e.target.value }))}
              className="w-32 h-8 text-sm"
            />
            <span className="text-sm text-muted-foreground">至</span>
            <Input
              type="time"
              value={prefs.quiet_hours_end}
              onChange={(e) => setPrefs((p) => ({ ...p, quiet_hours_end: e.target.value }))}
              className="w-32 h-8 text-sm"
            />
          </div>
        </CardContent>
      </Card>

      {/* Push limits */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">推送限制</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs text-muted-foreground">每日最大推送数</label>
            <Input
              type="number"
              min={0}
              value={prefs.max_daily_notifications}
              onChange={(e) =>
                setPrefs((p) => ({ ...p, max_daily_notifications: parseInt(e.target.value) || 0 }))
              }
              className="w-32 h-8 text-sm"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs text-muted-foreground">摘要间隔（分钟）</label>
            <Input
              type="number"
              min={1}
              value={prefs.digest_interval_minutes}
              onChange={(e) =>
                setPrefs((p) => ({
                  ...p,
                  digest_interval_minutes: parseInt(e.target.value) || 30,
                }))
              }
              className="w-32 h-8 text-sm"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs text-muted-foreground">最低置信度阈值</label>
            <div className="flex items-center gap-2">
              <Input
                type="number"
                min={0}
                max={100}
                value={prefs.min_confidence_threshold}
                onChange={(e) =>
                  setPrefs((p) => ({
                    ...p,
                    min_confidence_threshold: parseFloat(e.target.value) || 0,
                  }))
                }
                className="w-32 h-8 text-sm"
              />
              <span className="text-xs text-muted-foreground">%</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* User push channels */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">推送渠道</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            {USER_CHANNELS.map((ch) => (
              <Badge
                key={ch.value}
                variant={prefs.enabled_channels.includes(ch.value) ? "default" : "outline"}
                className="cursor-pointer text-xs"
                onClick={() => toggleUserChannel(ch.value)}
              >
                {ch.label}
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Diversity level */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">信息多样性</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-xs text-muted-foreground">
            控制推送信号的多样程度，防止信息茧房
          </p>
          {DIVERSITY_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className="flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2 transition-colors hover:bg-bg-hover data-[selected=true]:border-accent-primary data-[selected=true]:bg-accent-primary/5"
              data-selected={prefs.diversity_level === opt.value}
            >
              <input
                type="radio"
                name="diversity"
                value={opt.value}
                checked={prefs.diversity_level === opt.value}
                onChange={(e) => setPrefs((p) => ({ ...p, diversity_level: e.target.value }))}
                className="accent-[var(--accent-primary)]"
              />
              <div>
                <div className="text-sm font-medium">{opt.label}</div>
                <div className="text-xs text-muted-foreground">{opt.desc}</div>
              </div>
            </label>
          ))}
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={handleSavePrefs} disabled={prefsSaving} size="sm">
          {prefsSaving ? "保存中..." : "保存偏好"}
        </Button>
        {prefsSaved && <span className="text-xs text-info">已保存</span>}
      </div>

      {/* Advanced: system-level sentinel channels + data sources */}
      <Collapsible open={advancedOpen} onOpenChange={setAdvancedOpen}>
        <CollapsibleTrigger className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors">
          <ChevronDown
            className={`h-4 w-4 transition-transform ${advancedOpen ? "rotate-180" : ""}`}
          />
          高级配置 (系统通道)
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-4 space-y-6">
          {/* System Notification Channels */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <Bell className="h-4 w-4" />
                系统推送渠道
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {channels.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  暂无配置渠道。请编辑 config/sentinel.yaml 添加推送渠道。
                </p>
              ) : (
                channels.map((ch, i) => (
                  <ChannelCard
                    key={`${ch.type}-${i}`}
                    channel={ch}
                    eventTypes={eventTypes}
                    onToggle={(enabled) => handleToggleChannel(i, enabled)}
                    onToggleEvent={(event, add) => handleToggleEvent(i, event, add)}
                  />
                ))
              )}
              <p className="text-[10px] text-muted-foreground">
                敏感配置 (Token / URL) 通过环境变量注入，请参考 config/sentinel.yaml
              </p>
            </CardContent>
          </Card>

          {/* Data Sources */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <Globe className="h-4 w-4" />
                系统数据源 (Sentinel)
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                控制系统级数据采集源，与情报中心的源权重配置独立
              </p>
            </CardHeader>
            <CardContent className="space-y-3">
              <DataSourceRow
                label="全球市场"
                description="yfinance 全球指数、商品、汇率数据"
                enabled={dataSources.global_markets?.enabled ?? false}
                onToggle={(v) => handleToggleDataSource("global_markets", v)}
              />
              <DataSourceRow
                label="新闻平台"
                description={`${dataSources.news_platforms?.platforms?.length ?? 0} 个平台, ${(dataSources.news_platforms?.refresh_interval ?? 1800) / 60} 分钟刷新`}
                enabled={dataSources.news_platforms?.enabled ?? false}
                onToggle={(v) => handleToggleDataSource("news_platforms", v)}
              />
              <DataSourceRow
                label="RSS 订阅"
                description={`${dataSources.rss_feeds?.feeds?.length ?? 0} 个订阅源`}
                enabled={dataSources.rss_feeds?.enabled ?? false}
                onToggle={(v) => handleToggleDataSource("rss_feeds", v)}
              />
            </CardContent>
          </Card>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}

function ChannelCard({
  channel,
  eventTypes,
  onToggle,
  onToggleEvent,
}: {
  channel: NotificationChannel
  eventTypes: string[]
  onToggle: (enabled: boolean) => void
  onToggleEvent: (event: string, add: boolean) => void
}) {
  const cfg = CHANNEL_CONFIG[channel.type]
  const Icon = cfg?.icon ?? Bell
  const hasAll = channel.events.includes("all")

  return (
    <div className="border rounded-lg p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className={`h-4 w-4 ${cfg?.color ?? "text-muted-foreground"}`} />
          <span className="text-sm font-medium">{cfg?.label ?? channel.type}</span>
          {channel.enabled ? (
            <Badge className="bg-info/15 text-info text-[10px]">已启用</Badge>
          ) : (
            <Badge variant="secondary" className="text-[10px]">已禁用</Badge>
          )}
        </div>
        <Switch
          checked={channel.enabled}
          onCheckedChange={onToggle}
          className="scale-90"
        />
      </div>

      {channel.enabled && (
        <div className="pl-6 space-y-1">
          <p className="text-[10px] text-muted-foreground mb-1">订阅事件:</p>
          <div className="flex flex-wrap gap-1.5">
            {eventTypes.map((evt) => {
              const active = hasAll || channel.events.includes(evt)
              return (
                <button
                  key={evt}
                  className={`text-[10px] px-2 py-0.5 rounded-full border transition-colors ${
                    active
                      ? "bg-primary/10 border-primary/30 text-primary"
                      : "bg-muted border-transparent text-muted-foreground hover:border-muted-foreground/30"
                  }`}
                  onClick={() => onToggleEvent(evt, !active)}
                >
                  {EVENT_LABELS[evt] ?? evt}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

function DataSourceRow({
  label,
  description,
  enabled,
  onToggle,
}: {
  label: string
  description: string
  enabled: boolean
  onToggle: (v: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm font-medium">{label}</p>
        <p className="text-[11px] text-muted-foreground">{description}</p>
      </div>
      <Switch checked={enabled} onCheckedChange={onToggle} className="scale-90" />
    </div>
  )
}
