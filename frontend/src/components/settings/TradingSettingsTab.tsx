/** Trading settings tab — risk preference only (capital moved to Portfolio page). */

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { toast } from "sonner"
import { getUserConfig, updateUserConfig } from "@/api/user-config"

const RISK_OPTIONS = [
  { value: "conservative", label: "保守", desc: "优先安全，偏好低波动品种" },
  { value: "moderate", label: "稳健", desc: "风险与收益均衡" },
  { value: "aggressive", label: "积极", desc: "追求高收益，可承受较大波动" },
] as const

export function TradingSettingsTab() {
  const [risk, setRisk] = useState("moderate")
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getUserConfig()
      .then((config) => {
        if (config.risk_tolerance) setRisk(config.risk_tolerance)
      })
      .catch(() => toast.error("加载投资配置失败"))
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    try {
      await updateUserConfig({ risk_tolerance: risk })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {
      toast.error("保存失败，请重试")
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            加载中...
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">风险偏好</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">
            影响 Agent 给出建议的激进程度和品种选择。资金管理已移至「持仓」页面。
          </p>
          <div className="space-y-2">
            {RISK_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className="flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2 transition-colors hover:bg-bg-hover data-[selected=true]:border-accent-primary data-[selected=true]:bg-accent-primary/5"
                data-selected={risk === opt.value}
              >
                <input
                  type="radio"
                  name="risk"
                  value={opt.value}
                  checked={risk === opt.value}
                  onChange={(e) => setRisk(e.target.value)}
                  className="accent-[var(--accent-primary)]"
                />
                <div>
                  <div className="text-sm font-medium">{opt.label}</div>
                  <div className="text-xs text-muted-foreground">{opt.desc}</div>
                </div>
              </label>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={handleSave} disabled={saving} size="sm">
          {saving ? "保存中..." : "保存"}
        </Button>
        {saved && (
          <span className="text-xs text-info">已保存</span>
        )}
      </div>
    </div>
  )
}
