import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Play, Loader2, Clock, Coins, Cpu } from "lucide-react"
import { useTestPrompt } from "@/hooks/usePrompts"
import type { PromptTestResult } from "@/types/prompt"

interface Props {
  promptId: string
  variables: string[]
}

export function PromptTestPanel({ promptId, variables }: Props) {
  const [testVars, setTestVars] = useState<Record<string, string>>({})
  const [result, setResult] = useState<PromptTestResult | null>(null)
  const testMutation = useTestPrompt()

  const handleTest = () => {
    testMutation.mutate(
      { id: promptId, variables: testVars },
      { onSuccess: (data) => setResult(data) },
    )
  }

  return (
    <div className="space-y-4">
      {/* Variable inputs */}
      {variables.length > 0 && (
        <Card>
          <CardHeader className="py-3">
            <CardTitle className="text-xs">测试变量</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {variables.map((v) => (
              <div key={v} className="flex items-center gap-2">
                <code className="text-xs bg-muted px-1.5 py-0.5 rounded w-32 shrink-0 truncate">
                  {`{${v}}`}
                </code>
                <Input
                  placeholder={`输入 ${v} 的测试值...`}
                  value={testVars[v] || ""}
                  onChange={(e) =>
                    setTestVars((prev) => ({ ...prev, [v]: e.target.value }))
                  }
                  className="h-8 text-sm"
                />
              </div>
            ))}
            <Button
              size="sm"
              onClick={handleTest}
              disabled={testMutation.isPending}
              className="mt-2 gap-1"
            >
              {testMutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              执行测试
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Test result */}
      {result && (
        <Card>
          <CardHeader className="py-3">
            <CardTitle className="text-xs flex items-center justify-between">
              测试结果
              {result.status === "success" ? (
                <div className="flex items-center gap-3 text-[10px] text-muted-foreground font-normal">
                  {result.model && (
                    <span className="flex items-center gap-1">
                      <Cpu className="h-3 w-3" />
                      {result.model}
                    </span>
                  )}
                  {result.latency_ms != null && (
                    <span className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {result.latency_ms}ms
                    </span>
                  )}
                  {result.cost_usd != null && (
                    <span className="flex items-center gap-1">
                      <Coins className="h-3 w-3" />
                      ${result.cost_usd.toFixed(4)}
                    </span>
                  )}
                </div>
              ) : (
                <Badge variant="destructive" className="text-[10px]">
                  失败
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {result.status === "success" ? (
              <div className="space-y-3">
                {result.input_tokens != null && result.output_tokens != null && (
                  <div className="flex gap-3 text-xs text-muted-foreground">
                    <span>输入: {result.input_tokens} tokens</span>
                    <span>输出: {result.output_tokens} tokens</span>
                  </div>
                )}
                <pre className="text-xs bg-muted p-3 rounded-md overflow-auto max-h-80 whitespace-pre-wrap">
                  {result.response}
                </pre>
              </div>
            ) : (
              <p className="text-sm text-destructive">{result.message}</p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
