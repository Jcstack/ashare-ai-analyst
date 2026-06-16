import { AlertTriangle } from "lucide-react"

export function AIDisclaimer() {
  return (
    <div className="border-t pt-2 mt-3 flex items-start gap-1.5">
      <AlertTriangle className="h-3 w-3 text-muted-foreground/60 mt-0.5 shrink-0" />
      <p className="text-xs text-muted-foreground/60 leading-relaxed">
        AI 分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。
      </p>
    </div>
  )
}
