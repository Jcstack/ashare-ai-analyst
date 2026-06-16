import type { ReactNode } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Sparkles, RefreshCw, AlertCircle } from "lucide-react"
import { cn } from "@/lib/utils"

interface AIAnalysisCardProps {
  title: string
  icon?: ReactNode
  isLoading: boolean
  error: Error | null
  isEmpty: boolean
  emptyMessage?: string
  onRetry?: () => void
  onGenerate?: () => void
  isRetrying?: boolean
  generatedAt?: string | null
  children: ReactNode
}

function AILoadingState({ title }: { title: string }) {
  return (
    <Card className="border-l-2 border-l-[var(--accent-primary)]">
      <CardContent className="p-6">
        <div className="flex items-center gap-3">
          <RefreshCw className="h-5 w-5 text-accent-primary animate-spin" />
          <div>
            <p className="text-sm font-medium">{title}</p>
            <div className="flex items-center gap-2 mt-2">
              <span className="ai-dot" />
              <span className="ai-dot" />
              <span className="ai-dot" />
              <span className="text-xs text-muted-foreground ml-1">AI 正在分析中...</span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function AIErrorState({
  title,
  error,
  onRetry,
  isRetrying,
}: {
  title: string
  error: Error
  onRetry?: () => void
  isRetrying?: boolean
}) {
  return (
    <Card className="border-destructive/30">
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <AlertCircle className="h-4 w-4 text-destructive shrink-0" />
            <div className="min-w-0">
              <p className="text-sm font-medium">{title}</p>
              <p className="text-xs text-destructive mt-0.5 truncate">{error.message}</p>
            </div>
          </div>
          {onRetry && (
            <Button
              variant="outline"
              size="sm"
              onClick={onRetry}
              disabled={isRetrying}
              className="ml-3 shrink-0"
            >
              <RefreshCw className={cn("h-3.5 w-3.5 mr-1", isRetrying && "animate-spin")} />
              重试
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function AIEmptyState({
  title,
  icon,
  emptyMessage,
  onGenerate,
  isRetrying,
}: {
  title: string
  icon?: ReactNode
  emptyMessage?: string
  onGenerate?: () => void
  isRetrying?: boolean
}) {
  return (
    <Card className="border-l-2 border-l-[var(--accent-primary)]">
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {icon || <Sparkles className="h-5 w-5 text-accent-primary" />}
            <span className="text-title">{title}</span>
          </div>
          {onGenerate && (
            <Button
              variant="outline"
              size="sm"
              onClick={onGenerate}
              disabled={isRetrying}
            >
              <RefreshCw className={cn("h-4 w-4 mr-1", isRetrying && "animate-spin")} />
              生成分析
            </Button>
          )}
        </div>
        <p className="text-sm text-muted-foreground mt-2">
          {emptyMessage || "点击按钮生成AI分析报告"}
        </p>
      </CardContent>
    </Card>
  )
}

export function AIAnalysisCard({
  title,
  icon,
  isLoading,
  error,
  isEmpty,
  emptyMessage,
  onRetry,
  onGenerate,
  isRetrying,
  generatedAt,
  children,
}: AIAnalysisCardProps) {
  if (isLoading) {
    return <AILoadingState title={title} />
  }

  if (error) {
    return (
      <AIErrorState
        title={title}
        error={error}
        onRetry={onRetry}
        isRetrying={isRetrying}
      />
    )
  }

  if (isEmpty) {
    return (
      <AIEmptyState
        title={title}
        icon={icon}
        emptyMessage={emptyMessage}
        onGenerate={onGenerate}
        isRetrying={isRetrying}
      />
    )
  }

  return (
    <Card className="border-l-2 border-l-[var(--accent-primary)] overflow-hidden">
      <CardContent className="p-4 space-y-4">
        {children}
        {generatedAt && (
          <p className="text-micro text-muted-foreground/50 text-right">
            {new Date(generatedAt).toLocaleString("zh-CN")}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
