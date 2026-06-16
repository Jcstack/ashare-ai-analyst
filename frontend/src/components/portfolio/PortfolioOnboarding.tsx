import { Briefcase, Plus } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"

interface Props {
  onAddClick: () => void
}

export function PortfolioOnboarding({ onAddClick }: Props) {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center justify-center py-20 text-muted-foreground">
        <div className="rounded-full bg-muted p-4 mb-4">
          <Briefcase className="h-8 w-8" />
        </div>
        <p className="text-title text-foreground">开始管理你的持仓</p>
        <p className="text-caption mt-1 max-w-md text-center">
          添加你的A股持仓，系统将结合实时行情和技术指标，为你提供AI驱动的持仓诊断与调仓建议
        </p>
        <Button className="mt-6 gap-2" onClick={onAddClick}>
          <Plus className="h-4 w-4" />
          添加第一只持仓
        </Button>
      </CardContent>
    </Card>
  )
}
