import { useSearchParams } from "react-router-dom"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { NotificationSettingsTab } from "@/components/settings/NotificationSettingsTab"
import { AppearanceSettingsTab } from "@/components/settings/AppearanceSettingsTab"
import { TradingSettingsTab } from "@/components/settings/TradingSettingsTab"
import { LLMSettingsTab } from "@/components/settings/LLMSettingsTab"
import { UserFollowsSettingsTab } from "@/components/settings/UserFollowsSettingsTab"
import { IntelligencePrefsTab } from "@/components/settings/IntelligencePrefsTab"

const TABS = [
  { value: "appearance", label: "外观" },
  { value: "trading", label: "投资" },
  { value: "follows", label: "关注配置" },
  { value: "intelligence", label: "情报偏好" },
  { value: "notifications", label: "通知与推送" },
  { value: "llm", label: "AI 模型" },
]

export default function Settings() {
  const [searchParams, setSearchParams] = useSearchParams()

  const currentTab = searchParams.get("tab") || "appearance"
  const isValidTab = TABS.some((t) => t.value === currentTab)
  const effectiveTab = isValidTab ? currentTab : "appearance"

  const handleTabChange = (tab: string) => {
    setSearchParams({ tab })
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-headline">设置</h1>
        <p className="text-caption text-muted-foreground">查看和管理系统配置</p>
      </div>

      <Tabs value={effectiveTab} onValueChange={handleTabChange}>
        <TabsList variant="line">
          {TABS.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="appearance" className="mt-6">
          <AppearanceSettingsTab />
        </TabsContent>

        <TabsContent value="trading" className="mt-6">
          <TradingSettingsTab />
        </TabsContent>

        <TabsContent value="follows" className="mt-6">
          <UserFollowsSettingsTab />
        </TabsContent>

        <TabsContent value="intelligence" className="mt-6">
          <IntelligencePrefsTab />
        </TabsContent>

        <TabsContent value="notifications" className="mt-6">
          <NotificationSettingsTab />
        </TabsContent>

        <TabsContent value="llm" className="mt-6">
          <LLMSettingsTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
