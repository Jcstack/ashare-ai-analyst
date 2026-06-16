/** Category pill navigation for info hub sub-pages. */

import { cn } from "@/lib/utils"
import { SUB_PAGES } from "@/types/info-hub"

interface CategoryNavProps {
  /** The active sub-page key (category name or special key like "sources"). */
  activeSub: string | undefined
  onSubChange: (sub: string | undefined) => void
}

export function CategoryNav({ activeSub, onSubChange }: CategoryNavProps) {
  return (
    <div className="flex gap-2 flex-wrap">
      {SUB_PAGES.map((page) => {
        const isActive =
          (page.key === "all" && activeSub === undefined) ||
          page.key === activeSub ||
          (page.category !== undefined && page.category === activeSub)
        return (
          <button
            key={page.key}
            onClick={() => onSubChange(page.category ?? (page.key === "all" ? undefined : page.key))}
            className={cn(
              "px-3 py-1.5 rounded-full text-xs font-medium transition-colors",
              isActive
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            {page.label}
          </button>
        )
      })}
    </div>
  )
}
