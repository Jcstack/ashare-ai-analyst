import { useState, useEffect } from "react"
import { formatTime } from "@/lib/formatters"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  ArrowLeft,
  Save,
  Sparkles,
  Loader2,
  History,
  ChevronDown,
  ChevronUp,
} from "lucide-react"
import { usePrompt, useUpdatePrompt, useCreatePrompt, useOptimizePrompt } from "@/hooks/usePrompts"
import { PromptTestPanel } from "./PromptTestPanel"
import { PROMPT_CATEGORIES } from "@/types/prompt"
import type { PromptTemplate } from "@/types/prompt"

interface Props {
  promptId: string | null
  onBack: () => void
}

export function PromptEditor({ promptId, onBack }: Props) {
  const { data: prompt, isLoading } = usePrompt(promptId)
  const updateMutation = useUpdatePrompt()
  const createMutation = useCreatePrompt()
  const optimizeMutation = useOptimizePrompt()
  const [showHistory, setShowHistory] = useState(false)

  const [form, setForm] = useState<Partial<PromptTemplate>>({
    name: "",
    category: "custom",
    description: "",
    system_template: "",
    user_template: "",
    variables: [],
    tags: [],
  })

  const [tagInput, setTagInput] = useState("")
  const [varInput, setVarInput] = useState("")

  useEffect(() => {
    if (prompt) {
      setForm({
        name: prompt.name,
        category: prompt.category,
        description: prompt.description,
        system_template: prompt.system_template,
        user_template: prompt.user_template,
        variables: prompt.variables || [],
        tags: prompt.tags || [],
      })
    }
  }, [prompt])

  const isNew = !promptId

  const handleSave = () => {
    if (isNew) {
      createMutation.mutate(form, { onSuccess: onBack })
    } else {
      updateMutation.mutate({ id: promptId!, data: form }, { onSuccess: onBack })
    }
  }

  const handleOptimize = () => {
    if (!promptId) return
    optimizeMutation.mutate({ id: promptId })
  }

  const addTag = () => {
    const tag = tagInput.trim()
    if (tag && !form.tags?.includes(tag)) {
      setForm((prev) => ({ ...prev, tags: [...(prev.tags || []), tag] }))
    }
    setTagInput("")
  }

  const removeTag = (tag: string) => {
    setForm((prev) => ({ ...prev, tags: (prev.tags || []).filter((t) => t !== tag) }))
  }

  const addVar = () => {
    const v = varInput.trim()
    if (v && !form.variables?.includes(v)) {
      setForm((prev) => ({ ...prev, variables: [...(prev.variables || []), v] }))
    }
    setVarInput("")
  }

  const removeVar = (v: string) => {
    setForm((prev) => ({
      ...prev,
      variables: (prev.variables || []).filter((x) => x !== v),
    }))
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  const isSaving = updateMutation.isPending || createMutation.isPending

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={onBack} className="gap-1">
          <ArrowLeft className="h-4 w-4" />
          返回列表
        </Button>
        <div className="flex items-center gap-2">
          {promptId && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleOptimize}
              disabled={optimizeMutation.isPending}
              className="gap-1"
            >
              {optimizeMutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Sparkles className="h-3.5 w-3.5" />
              )}
              AI 优化
            </Button>
          )}
          <Button size="sm" onClick={handleSave} disabled={isSaving} className="gap-1">
            {isSaving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            {isNew ? "创建" : "保存"}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Left: Editor */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="py-3">
              <CardTitle className="text-xs">基本信息</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <label className="text-xs text-muted-foreground">名称</label>
                <Input
                  value={form.name || ""}
                  onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
                  placeholder="Prompt 名称"
                  className="h-8 text-sm mt-1"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">分类</label>
                <Select
                  value={form.category || "custom"}
                  onValueChange={(val) => setForm((prev) => ({ ...prev, category: val }))}
                >
                  <SelectTrigger className="h-8 text-sm mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(PROMPT_CATEGORIES).map(([k, v]) => (
                      <SelectItem key={k} value={k}>
                        {v}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground">描述</label>
                <Input
                  value={form.description || ""}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, description: e.target.value }))
                  }
                  placeholder="简要描述..."
                  className="h-8 text-sm mt-1"
                />
              </div>

              {/* Tags */}
              <div>
                <label className="text-xs text-muted-foreground">标签</label>
                <div className="flex flex-wrap gap-1 mt-1">
                  {(form.tags || []).map((tag) => (
                    <Badge
                      key={tag}
                      variant="secondary"
                      className="text-xs cursor-pointer"
                      onClick={() => removeTag(tag)}
                    >
                      {tag} ×
                    </Badge>
                  ))}
                </div>
                <div className="flex gap-1 mt-1">
                  <Input
                    value={tagInput}
                    onChange={(e) => setTagInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addTag())}
                    placeholder="添加标签..."
                    className="h-7 text-xs flex-1"
                  />
                  <Button variant="outline" size="sm" onClick={addTag} className="h-7 text-xs">
                    添加
                  </Button>
                </div>
              </div>

              {/* Variables */}
              <div>
                <label className="text-xs text-muted-foreground">变量</label>
                <div className="flex flex-wrap gap-1 mt-1">
                  {(form.variables || []).map((v) => (
                    <Badge
                      key={v}
                      variant="outline"
                      className="text-xs cursor-pointer font-mono"
                      onClick={() => removeVar(v)}
                    >
                      {`{${v}}`} ×
                    </Badge>
                  ))}
                </div>
                <div className="flex gap-1 mt-1">
                  <Input
                    value={varInput}
                    onChange={(e) => setVarInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addVar())}
                    placeholder="添加变量名..."
                    className="h-7 text-xs flex-1"
                  />
                  <Button variant="outline" size="sm" onClick={addVar} className="h-7 text-xs">
                    添加
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="py-3">
              <CardTitle className="text-xs">System Template</CardTitle>
            </CardHeader>
            <CardContent>
              <Textarea
                value={form.system_template || ""}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, system_template: e.target.value }))
                }
                placeholder="System prompt 模板..."
                className="font-mono text-xs min-h-[200px]"
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="py-3">
              <CardTitle className="text-xs">User Template</CardTitle>
            </CardHeader>
            <CardContent>
              <Textarea
                value={form.user_template || ""}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, user_template: e.target.value }))
                }
                placeholder="User prompt 模板（使用 {variable} 语法）..."
                className="font-mono text-xs min-h-[200px]"
              />
            </CardContent>
          </Card>

          {/* Version History */}
          {prompt?.version_history && prompt.version_history.length > 0 && (
            <Card>
              <CardHeader className="py-3">
                <CardTitle
                  className="text-xs flex items-center gap-1 cursor-pointer"
                  onClick={() => setShowHistory(!showHistory)}
                >
                  <History className="h-3.5 w-3.5" />
                  版本历史 ({prompt.version_history.length})
                  {showHistory ? (
                    <ChevronUp className="h-3 w-3 ml-auto" />
                  ) : (
                    <ChevronDown className="h-3 w-3 ml-auto" />
                  )}
                </CardTitle>
              </CardHeader>
              {showHistory && (
                <CardContent className="space-y-2">
                  {prompt.version_history
                    .slice()
                    .reverse()
                    .map((v) => (
                      <div key={v.version} className="border rounded p-2 text-xs">
                        <div className="flex items-center justify-between mb-1">
                          <Badge variant="outline" className="text-[10px]">
                            v{v.version}
                          </Badge>
                          <span className="text-muted-foreground">{formatTime(v.timestamp)}</span>
                        </div>
                        <pre className="text-[10px] bg-muted p-1.5 rounded max-h-20 overflow-auto whitespace-pre-wrap">
                          {v.system_template?.slice(0, 200)}...
                        </pre>
                      </div>
                    ))}
                </CardContent>
              )}
            </Card>
          )}
        </div>

        {/* Right: Test Panel + AI Optimize Results */}
        <div className="space-y-4">
          {promptId && (
            <PromptTestPanel
              promptId={promptId}
              variables={form.variables || []}
            />
          )}

          {/* AI Optimization Results */}
          {optimizeMutation.data && optimizeMutation.data.status === "success" && (
            <Card className="border-l-2 border-l-[var(--accent-primary)]">
              <CardHeader className="py-3">
                <CardTitle className="text-xs flex items-center gap-1">
                  <Sparkles className="h-3.5 w-3.5 text-accent-primary" />
                  AI 优化建议
                  {optimizeMutation.data.overall_score != null && (
                    <Badge variant="outline" className="text-[10px] ml-auto">
                      评分: {optimizeMutation.data.overall_score}/100
                    </Badge>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {optimizeMutation.data.suggestions?.map((s, i) => (
                  <div key={i} className="border rounded p-2 text-xs space-y-1">
                    <div className="flex items-center gap-2">
                      <Badge
                        variant={
                          s.priority === "high"
                            ? "destructive"
                            : s.priority === "medium"
                              ? "default"
                              : "secondary"
                        }
                        className="text-[10px]"
                      >
                        {s.priority}
                      </Badge>
                      <span className="font-medium">{s.aspect}</span>
                    </div>
                    <p className="text-muted-foreground">{s.issue}</p>
                    <p>{s.recommendation}</p>
                  </div>
                ))}

                {optimizeMutation.data.improved_system_template && (
                  <div>
                    <p className="text-xs font-medium mb-1">优化后 System Template:</p>
                    <pre className="text-[10px] bg-muted p-2 rounded max-h-40 overflow-auto whitespace-pre-wrap">
                      {optimizeMutation.data.improved_system_template}
                    </pre>
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-1 text-xs h-7"
                      onClick={() =>
                        setForm((prev) => ({
                          ...prev,
                          system_template:
                            optimizeMutation.data?.improved_system_template || prev.system_template,
                        }))
                      }
                    >
                      应用优化
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
