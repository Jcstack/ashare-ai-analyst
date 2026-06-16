import { Badge } from "@/components/ui/badge"
import { DATA_SOURCE_LABELS } from "@/types/prediction"
import type { DataSource } from "@/types/prediction"

interface SourceSelectorProps {
  selected: DataSource[]
  onChange: (sources: DataSource[]) => void
}

const ALL_SOURCES: DataSource[] = [
  "indicators",
  "fund_flow",
  "dragon_tiger",
  "bayesian",
  "news",
  "risk",
]

export function SourceSelector({ selected, onChange }: SourceSelectorProps) {
  const toggle = (source: DataSource) => {
    if (selected.includes(source)) {
      onChange(selected.filter((s) => s !== source))
    } else {
      onChange([...selected, source])
    }
  }

  return (
    <div>
      <label className="text-caption text-muted-foreground mb-2 block">数据源</label>
      <div className="flex flex-wrap gap-2">
        {ALL_SOURCES.map((source) => {
          const isSelected = selected.includes(source)
          return (
            <Badge
              key={source}
              variant={isSelected ? "default" : "outline"}
              className="cursor-pointer select-none transition-colors"
              onClick={() => toggle(source)}
            >
              {DATA_SOURCE_LABELS[source]}
            </Badge>
          )
        })}
      </div>
    </div>
  )
}
