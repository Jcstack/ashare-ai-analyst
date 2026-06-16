import { useState, useEffect } from "react"
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogAction,
} from "@/components/ui/alert-dialog"
import { BarChart3, Brain, Shield } from "lucide-react"

const STORAGE_KEY = "onboarding-completed"

export function OnboardingDialog() {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const completed = localStorage.getItem(STORAGE_KEY)
    if (!completed) {
      setOpen(true)
    }
  }, [])

  const handleStart = () => {
    localStorage.setItem(STORAGE_KEY, "true")
    setOpen(false)
  }

  return (
    <AlertDialog open={open}>
      <AlertDialogContent className="max-w-md" data-testid="onboarding-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-xl text-center">
            你好！欢迎使用 AI 智能投顾
          </AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="space-y-4 pt-2">
              <p className="text-sm text-center text-muted-foreground">
                我可以帮你更聪明地做投资决策
              </p>
              <div className="space-y-3">
                <div className="flex items-start gap-3 rounded-lg border p-3">
                  <Brain className="h-5 w-5 text-primary mt-0.5 shrink-0" />
                  <div>
                    <p className="text-sm font-medium">AI 分析 A 股</p>
                    <p className="text-xs text-muted-foreground">输入任何一只股票，AI 帮你分析趋势、风险和操作建议</p>
                  </div>
                </div>
                <div className="flex items-start gap-3 rounded-lg border p-3">
                  <BarChart3 className="h-5 w-5 text-primary mt-0.5 shrink-0" />
                  <div>
                    <p className="text-sm font-medium">看懂专业术语</p>
                    <p className="text-xs text-muted-foreground">不懂 RSI、MACD？鼠标悬停即可看到大白话解释</p>
                  </div>
                </div>
                <div className="flex items-start gap-3 rounded-lg border p-3">
                  <Shield className="h-5 w-5 text-primary mt-0.5 shrink-0" />
                  <div>
                    <p className="text-sm font-medium">追踪持仓与风险</p>
                    <p className="text-xs text-muted-foreground">记录你的持仓，AI 持续监控并提醒潜在风险</p>
                  </div>
                </div>
              </div>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter className="pt-2">
          <AlertDialogAction onClick={handleStart} className="w-full">
            开始使用
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
