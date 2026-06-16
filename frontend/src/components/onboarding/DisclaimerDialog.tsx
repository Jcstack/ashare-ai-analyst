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
import { AlertTriangle } from "lucide-react"

const STORAGE_KEY = "disclaimer-accepted"

export function DisclaimerDialog() {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const accepted = localStorage.getItem(STORAGE_KEY)
    if (!accepted) {
      // Show after a short delay to avoid collision with onboarding
      const timer = setTimeout(() => {
        const onboardingDone = localStorage.getItem("onboarding-completed")
        if (onboardingDone) {
          setOpen(true)
        } else {
          // Wait for onboarding to complete, then show
          const observer = new MutationObserver(() => {
            if (localStorage.getItem("onboarding-completed")) {
              setOpen(true)
              observer.disconnect()
            }
          })
          // Poll localStorage since storage events only fire across tabs
          const pollId = setInterval(() => {
            if (localStorage.getItem("onboarding-completed")) {
              setOpen(true)
              clearInterval(pollId)
            }
          }, 500)
          return () => clearInterval(pollId)
        }
      }, 300)
      return () => clearTimeout(timer)
    }
  }, [])

  const handleAccept = () => {
    localStorage.setItem(STORAGE_KEY, "true")
    setOpen(false)
  }

  return (
    <AlertDialog open={open}>
      <AlertDialogContent
        className="max-w-md"
        onEscapeKeyDown={(e: KeyboardEvent) => e.preventDefault()}
      >
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2 text-lg">
            <AlertTriangle className="h-5 w-5 text-warning" />
            免责声明
          </AlertDialogTitle>
          <AlertDialogDescription className="text-sm leading-relaxed">
            本系统所有分析结论均由 AI 模型生成，仅供学习参考，<strong className="text-foreground">不构成任何投资建议</strong>。
            <br /><br />
            股市有风险，投资需谨慎。您据此进行的任何投资操作，风险自担。
            <br /><br />
            数据来源包括 AKShare、东方财富等公开渠道，可能存在延迟或不准确。请以官方数据为准。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogAction onClick={handleAccept} className="w-full">
            我已了解，开始使用
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
