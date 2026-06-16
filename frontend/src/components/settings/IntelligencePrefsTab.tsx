/** Intelligence preferences tab — diversity, domain interests, source toggles. */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Switch } from "@/components/ui/switch"
import { Badge } from "@/components/ui/badge"
import { useInfoHubStore } from "@/stores/infoHubStore"
import { useSourcesHealth } from "@/hooks/useInfoHub"

// ─── Diversity ───────────────────────────────────────────────────────────────

const DIVERSITY_OPTIONS = [
  {
    value: "low" as const,
    label: "低",
    pct: "15%",
    desc: "优先展示与关注领域高度匹配的情报，少量探索性内容",
  },
  {
    value: "medium" as const,
    label: "中",
    pct: "30%",
    desc: "平衡关注领域与新领域的情报，适度拓展视野",
  },
  {
    value: "high" as const,
    label: "高",
    pct: "50%",
    desc: "大幅引入跨领域情报，鼓励发现意外关联与机会",
  },
]

// ─── Domain interests ────────────────────────────────────────────────────────

const DOMAIN_OPTIONS = [
  { id: "政策", label: "政策" },
  { id: "宏观", label: "宏观" },
  { id: "行业", label: "行业" },
  { id: "公司", label: "公司" },
  { id: "市场", label: "市场" },
  { id: "全球", label: "全球" },
  { id: "科技", label: "科技" },
  { id: "能源", label: "能源" },
  { id: "健康", label: "健康" },
  { id: "体育", label: "体育" },
]

// ─── Component ───────────────────────────────────────────────────────────────

export function IntelligencePrefsTab() {
  const diversityStrength = useInfoHubStore((s) => s.diversityStrength)
  const setDiversityStrength = useInfoHubStore((s) => s.setDiversityStrength)
  const userDomains = useInfoHubStore((s) => s.userDomains)
  const setUserDomains = useInfoHubStore((s) => s.setUserDomains)
  const disabledSources = useInfoHubStore((s) => s.disabledSources)
  const toggleSourceEnabled = useInfoHubStore((s) => s.toggleSourceEnabled)

  const { data: sources } = useSourcesHealth()

  const handleDomainToggle = (domainId: string) => {
    if (userDomains.includes(domainId)) {
      setUserDomains(userDomains.filter((d) => d !== domainId))
    } else {
      setUserDomains([...userDomains, domainId])
    }
  }

  return (
    <div className="space-y-6">
      {/* Section 1: Diversity Controls */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">多样性控制</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">
            控制情报流中探索性内容的占比。更高的多样性会引入更多关注领域之外的信息。
          </p>
          <div className="space-y-2">
            {DIVERSITY_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className="flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2 transition-colors hover:bg-bg-hover data-[selected=true]:border-accent-primary data-[selected=true]:bg-accent-primary/5"
                data-selected={diversityStrength === opt.value}
              >
                <input
                  type="radio"
                  name="diversity"
                  value={opt.value}
                  checked={diversityStrength === opt.value}
                  onChange={() => setDiversityStrength(opt.value)}
                  className="accent-[var(--accent-primary)]"
                />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{opt.label}</span>
                    <span className="text-xs tabular-nums text-muted-foreground">
                      ({opt.pct})
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground">{opt.desc}</div>
                </div>
              </label>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Section 2: Domain Interests */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">兴趣领域</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">
            选择关注的领域，多样性重排序会围绕这些领域调整情报优先级。
          </p>
          <div className="grid grid-cols-5 gap-3">
            {DOMAIN_OPTIONS.map((domain) => {
              const checked = userDomains.includes(domain.id)
              return (
                <label
                  key={domain.id}
                  className="flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 transition-colors hover:bg-bg-hover data-[selected=true]:border-accent-primary data-[selected=true]:bg-accent-primary/5"
                  data-selected={checked}
                >
                  <Checkbox
                    checked={checked}
                    onCheckedChange={() => handleDomainToggle(domain.id)}
                  />
                  <span className="text-sm">{domain.label}</span>
                </label>
              )
            })}
          </div>
          {userDomains.length === 0 && (
            <p className="text-xs text-yellow-500">
              未选择任何领域，多样性重排序将不会生效。
            </p>
          )}
        </CardContent>
      </Card>

      {/* Section 3: Source Weight Overrides */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">源权重覆写</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">
            查看各情报源的基础权重，可启用或禁用单个源的信息接入。
          </p>
          {sources && sources.length > 0 ? (
            <div className="space-y-1">
              {[...sources]
                .sort((a, b) => b.base_weight - a.base_weight)
                .map((source) => {
                  const enabled = !disabledSources.includes(source.source_id)
                  return (
                    <div
                      key={source.source_id}
                      className="flex items-center justify-between rounded-md border px-3 py-2 transition-colors hover:bg-bg-hover"
                    >
                      <div className="flex items-center gap-3">
                        <Switch
                          size="sm"
                          checked={enabled}
                          onCheckedChange={() =>
                            toggleSourceEnabled(source.source_id)
                          }
                        />
                        <span
                          className={`text-sm ${enabled ? "text-foreground" : "text-muted-foreground line-through"}`}
                        >
                          {formatSourceId(source.source_id)}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge
                          variant="outline"
                          className="text-[10px] tabular-nums"
                        >
                          权重 {source.base_weight.toFixed(2)}
                        </Badge>
                        {source.domain_tags.slice(0, 3).map((tag) => (
                          <Badge
                            key={tag}
                            variant="secondary"
                            className="text-[10px] px-1.5 py-0"
                          >
                            {tag}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )
                })}
            </div>
          ) : (
            <div className="py-4 text-center text-sm text-muted-foreground">
              暂无源数据
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function formatSourceId(id: string): string {
  return id
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
}
