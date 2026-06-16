/** Investment style settings — full style, sector, session, blacklist config.
 *
 * Per PRD v28.0 FR-REC063: Investment style configuration UI.
 */

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { toast } from "sonner"
import { X, Plus } from "lucide-react"
import { fetchPreferences, updateFullPreferences } from "@/api/recommendations"
import type { InvestmentStyleConfig } from "@/types/recommendation"

const STYLE_OPTIONS: { key: string; label: string; desc: string }[] = [
  { key: "value", label: "价值投资", desc: "低估值、高分红" },
  { key: "growth", label: "成长投资", desc: "高增长、高盈利" },
  { key: "momentum", label: "动量交易", desc: "趋势跟随、量价齐升" },
  { key: "swing", label: "波段交易", desc: "波动套利、技术面" },
  { key: "dividend", label: "红利收息", desc: "稳定分红、长期持有" },
  { key: "sector", label: "板块轮动", desc: "行业轮动、资金流向" },
]

const SESSION_OPTIONS: { key: string; label: string }[] = [
  { key: "pre_market", label: "盘前 (07:00-09:15)" },
  { key: "early", label: "早盘 (09:30-10:30)" },
  { key: "mid", label: "盘中 (10:30-14:00)" },
  { key: "late", label: "尾盘 (14:00-15:00)" },
  { key: "post_market", label: "盘后 (15:00-17:00)" },
]

const DEFAULT_CONFIG: InvestmentStyleConfig = {
  styles: ["value"],
  sector_preferences: [],
  blacklist: [],
  session_toggles: {
    pre_market: true,
    early: true,
    mid: true,
    late: true,
    post_market: true,
  },
}

function TagInput({
  items,
  placeholder,
  onAdd,
  onRemove,
  maxItems,
}: {
  items: string[]
  placeholder: string
  onAdd: (v: string) => void
  onRemove: (v: string) => void
  maxItems?: number
}) {
  const [input, setInput] = useState("")

  const handleAdd = () => {
    const v = input.trim()
    if (v && !items.includes(v) && (!maxItems || items.length < maxItems)) {
      onAdd(v)
      setInput("")
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={placeholder}
          className="h-8 text-sm"
          onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), handleAdd())}
          disabled={maxItems !== undefined && items.length >= maxItems}
        />
        <Button
          variant="outline"
          size="sm"
          className="h-8 px-2"
          onClick={handleAdd}
          disabled={maxItems !== undefined && items.length >= maxItems}
        >
          <Plus className="h-3.5 w-3.5" />
        </Button>
      </div>
      {items.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {items.map((item) => (
            <Badge key={item} variant="secondary" className="gap-1 text-xs">
              {item}
              <button onClick={() => onRemove(item)} className="hover:text-destructive">
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  )
}

export function InvestmentStyleSettingsTab() {
  const [config, setConfig] = useState<InvestmentStyleConfig>(DEFAULT_CONFIG)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchPreferences()
      .then((data) => setConfig({ ...DEFAULT_CONFIG, ...data }))
      .catch(() => toast.error("加载选股偏好失败"))
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    try {
      const updated = await updateFullPreferences(config)
      setConfig({ ...DEFAULT_CONFIG, ...updated })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {
      toast.error("保存失败，请重试")
    } finally {
      setSaving(false)
    }
  }

  const toggleStyle = (key: string) => {
    setConfig((prev) => {
      const styles = prev.styles.includes(key)
        ? prev.styles.filter((s) => s !== key)
        : prev.styles.length < 3
          ? [...prev.styles, key]
          : prev.styles
      return { ...prev, styles: styles.length > 0 ? styles : prev.styles }
    })
  }

  const toggleSession = (key: string) => {
    setConfig((prev) => ({
      ...prev,
      session_toggles: {
        ...prev.session_toggles,
        [key]: !prev.session_toggles[key],
      },
    }))
  }

  if (loading) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          加载中...
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      {/* Style selection */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">投资风格</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground mb-3">
            选择 1-3 种投资风格，系统将基于所选风格进行智能选股
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {STYLE_OPTIONS.map((opt) => (
              <button
                key={opt.key}
                onClick={() => toggleStyle(opt.key)}
                className={`rounded-lg border p-3 text-left transition-colors ${
                  config.styles.includes(opt.key)
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-primary/50"
                }`}
              >
                <div className="text-sm font-medium">{opt.label}</div>
                <div className="text-[10px] text-muted-foreground mt-0.5">
                  {opt.desc}
                </div>
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Sector preferences */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">行业偏好</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground mb-3">
            最多选择 5 个偏好行业，系统将优先推荐相关行业个股（保留 20% 跨行业发现）
          </p>
          <TagInput
            items={config.sector_preferences}
            placeholder="输入行业名称，如 白酒、新能源"
            maxItems={5}
            onAdd={(v) =>
              setConfig((prev) => ({
                ...prev,
                sector_preferences: [...prev.sector_preferences, v],
              }))
            }
            onRemove={(v) =>
              setConfig((prev) => ({
                ...prev,
                sector_preferences: prev.sector_preferences.filter((s) => s !== v),
              }))
            }
          />
        </CardContent>
      </Card>

      {/* Session toggles */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">推送时段</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground mb-3">
            控制每个交易时段是否接收推荐推送通知
          </p>
          <div className="space-y-3">
            {SESSION_OPTIONS.map((opt) => (
              <div key={opt.key} className="flex items-center justify-between">
                <Label htmlFor={`session-${opt.key}`} className="text-sm cursor-pointer">
                  {opt.label}
                </Label>
                <Switch
                  id={`session-${opt.key}`}
                  checked={config.session_toggles[opt.key] ?? true}
                  onCheckedChange={() => toggleSession(opt.key)}
                />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Blacklist */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">排除列表</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground mb-3">
            添加不希望被推荐的股票代码
          </p>
          <TagInput
            items={config.blacklist}
            placeholder="输入股票代码，如 600519"
            onAdd={(v) =>
              setConfig((prev) => ({
                ...prev,
                blacklist: [...prev.blacklist, v],
              }))
            }
            onRemove={(v) =>
              setConfig((prev) => ({
                ...prev,
                blacklist: prev.blacklist.filter((s) => s !== v),
              }))
            }
          />
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={handleSave} disabled={saving} size="sm">
          {saving ? "保存中..." : "保存"}
        </Button>
        {saved && <span className="text-xs text-info">已保存</span>}
      </div>
    </div>
  )
}
