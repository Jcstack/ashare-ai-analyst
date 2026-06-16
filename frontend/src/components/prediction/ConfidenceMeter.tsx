import { Progress } from "@/components/ui/progress"

interface ConfidenceMeterProps {
  confidence: number
}

export function ConfidenceMeter({ confidence }: ConfidenceMeterProps) {
  const color =
    confidence >= 70 ? "#66BB6A" : confidence >= 40 ? "#FFA726" : "#EF5350"

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className="text-muted-foreground">置信度</span>
        <span className="font-mono font-bold" style={{ color }}>
          {confidence}%
        </span>
      </div>
      <Progress value={confidence} className="h-2" />
    </div>
  )
}
