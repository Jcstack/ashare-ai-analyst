/** User follows settings — 8-dimension follow editor. */

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { toast } from "sonner"
import { getUserFollows, updateUserFollows } from "@/api/user-config"
import type { UserFollows } from "@/types/intelligence"
import { SIGNAL_TYPE_LABELS, RISK_LEVEL_LABELS } from "@/types/intelligence"
import type { SignalType, RiskLevel } from "@/types/intelligence"
import { X, Plus } from "lucide-react"

const DIMENSIONS: { key: keyof UserFollows; label: string; placeholder: string }[] = [
  { key: "stocks", label: "股票代码", placeholder: "输入股票代码，如 600519" },
  { key: "sectors", label: "行业板块", placeholder: "输入行业名称，如 白酒" },
  { key: "concepts", label: "概念题材", placeholder: "输入概念名称，如 AI" },
  { key: "keywords", label: "关键词", placeholder: "输入关注关键词" },
  { key: "indices", label: "指数", placeholder: "输入指数代码，如 000001" },
  { key: "macro_factors", label: "宏观因子", placeholder: "输入因子名称，如 CPI" },
]

const ALL_SIGNAL_TYPES = Object.keys(SIGNAL_TYPE_LABELS) as SignalType[]
const ALL_RISK_LEVELS = Object.keys(RISK_LEVEL_LABELS) as RiskLevel[]

function TagInput({
  items,
  placeholder,
  onAdd,
  onRemove,
}: {
  items: string[]
  placeholder: string
  onAdd: (v: string) => void
  onRemove: (v: string) => void
}) {
  const [input, setInput] = useState("")

  const handleAdd = () => {
    const v = input.trim()
    if (v && !items.includes(v)) {
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
        />
        <Button variant="outline" size="sm" className="h-8 px-2" onClick={handleAdd}>
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

const EMPTY_FOLLOWS: UserFollows = {
  stocks: [], sectors: [], concepts: [], signal_types: [],
  risk_levels: [], keywords: [], indices: [], macro_factors: [],
}

export function UserFollowsSettingsTab() {
  const [follows, setFollows] = useState<UserFollows>(EMPTY_FOLLOWS)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getUserFollows()
      .then(setFollows)
      .catch(() => toast.error("加载关注配置失败"))
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    try {
      const updated = await updateUserFollows(follows)
      setFollows(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {
      toast.error("保存失败，请重试")
    } finally {
      setSaving(false)
    }
  }

  const addItem = (key: keyof UserFollows, value: string) => {
    setFollows((prev) => ({ ...prev, [key]: [...prev[key], value] }))
  }

  const removeItem = (key: keyof UserFollows, value: string) => {
    setFollows((prev) => ({ ...prev, [key]: prev[key].filter((v) => v !== value) }))
  }

  const toggleItem = (key: keyof UserFollows, value: string) => {
    setFollows((prev) => {
      const list = prev[key]
      return {
        ...prev,
        [key]: list.includes(value) ? list.filter((v) => v !== value) : [...list, value],
      }
    })
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
      {/* Free-text dimensions */}
      {DIMENSIONS.map((dim) => (
        <Card key={dim.key}>
          <CardHeader>
            <CardTitle className="text-sm">{dim.label}</CardTitle>
          </CardHeader>
          <CardContent>
            <TagInput
              items={follows[dim.key]}
              placeholder={dim.placeholder}
              onAdd={(v) => addItem(dim.key, v)}
              onRemove={(v) => removeItem(dim.key, v)}
            />
          </CardContent>
        </Card>
      ))}

      {/* Signal types — toggle chips */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">信号类型</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground mb-3">选择关注的信号类型</p>
          <div className="flex flex-wrap gap-2">
            {ALL_SIGNAL_TYPES.map((st) => (
              <Badge
                key={st}
                variant={follows.signal_types.includes(st) ? "default" : "outline"}
                className="cursor-pointer text-xs"
                onClick={() => toggleItem("signal_types", st)}
              >
                {SIGNAL_TYPE_LABELS[st]}
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Risk levels — toggle chips */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">风险等级</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground mb-3">选择需要通知的风险等级</p>
          <div className="flex flex-wrap gap-2">
            {ALL_RISK_LEVELS.map((rl) => (
              <Badge
                key={rl}
                variant={follows.risk_levels.includes(rl) ? "default" : "outline"}
                className="cursor-pointer text-xs"
                onClick={() => toggleItem("risk_levels", rl)}
              >
                {RISK_LEVEL_LABELS[rl]}
              </Badge>
            ))}
          </div>
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
