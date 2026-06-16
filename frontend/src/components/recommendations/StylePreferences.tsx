/** Style selection component for recommendation preferences. */

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { InvestmentStyle } from "@/types/recommendation"

export function StylePreferences({
  styles,
  selected,
  onSelect,
}: {
  styles: InvestmentStyle[]
  selected: string | null
  onSelect: (style: string | null) => void
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <Badge
        variant={selected === null ? "default" : "outline"}
        className={cn(
          "cursor-pointer transition-all",
          selected === null && "ring-1 ring-primary"
        )}
        onClick={() => onSelect(null)}
      >
        全部
      </Badge>
      {styles.map((s) => (
        <Badge
          key={s.key}
          variant={selected === s.key ? "default" : "outline"}
          className={cn(
            "cursor-pointer transition-all",
            selected === s.key && "ring-1 ring-primary"
          )}
          onClick={() => onSelect(s.key)}
        >
          {s.label}
        </Badge>
      ))}
    </div>
  )
}
