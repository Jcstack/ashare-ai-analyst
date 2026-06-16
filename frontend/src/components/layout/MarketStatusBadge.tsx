import { useMarketStatus } from "@/hooks/useMarketStatus"
import { cn } from "@/lib/utils"

const STATUS_STYLES: Record<string, { dot: string; text: string; pulse?: boolean }> = {
  trading:    { dot: "bg-green-500",  text: "text-green-600 dark:text-green-400" },
  closed:     { dot: "bg-red-500",    text: "text-red-600 dark:text-red-400" },
  holiday:    { dot: "bg-red-500",    text: "text-red-600 dark:text-red-400" },
  lunch:      { dot: "bg-yellow-500", text: "text-yellow-600 dark:text-yellow-400" },
  pre_market: { dot: "bg-orange-500", text: "text-orange-600 dark:text-orange-400" },
  emergency:  { dot: "bg-red-600",    text: "text-red-600 dark:text-red-400", pulse: true },
}

export function MarketStatusBadge({ compact = false }: { compact?: boolean }) {
  const { data: status } = useMarketStatus()

  if (!status) return null

  const style = STATUS_STYLES[status.status] ?? STATUS_STYLES.closed

  return (
    <div className={cn(
      "flex items-center gap-1.5",
      compact ? "text-[11px]" : "text-xs",
    )}>
      <span
        className={cn(
          "inline-block h-2 w-2 rounded-full shrink-0",
          style.dot,
          style.pulse && "animate-pulse",
        )}
      />
      <span className={cn("font-medium whitespace-nowrap", style.text)}>
        {status.label}
      </span>
    </div>
  )
}
