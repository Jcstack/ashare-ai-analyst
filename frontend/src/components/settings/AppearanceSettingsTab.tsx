import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export function AppearanceSettingsTab() {
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">主题设置</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            使用左侧栏底部的太阳/月亮图标切换明暗主题。
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
