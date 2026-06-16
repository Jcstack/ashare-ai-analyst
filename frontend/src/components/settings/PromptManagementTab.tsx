import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Loader2, Plus, Pencil, Trash2 } from "lucide-react"
import { usePrompts, useDeletePrompt } from "@/hooks/usePrompts"
import { PromptEditor } from "./PromptEditor"
import { PROMPT_CATEGORIES } from "@/types/prompt"
import { toast } from "sonner"

export function PromptManagementTab() {
  const { data: prompts, isLoading } = usePrompts()
  const deleteMutation = useDeletePrompt()
  const [editingId, setEditingId] = useState<string | null | "new">(null)
  const [deleteTarget, setDeleteTarget] = useState<{
    id: string
    name: string
  } | null>(null)

  const confirmDelete = () => {
    if (deleteTarget) {
      deleteMutation.mutate(deleteTarget.id, {
        onSuccess: () => {
          toast.success(`已删除 ${deleteTarget.name}`)
          setDeleteTarget(null)
        },
        onError: () => {
          toast.error("删除失败")
          setDeleteTarget(null)
        },
      })
    }
  }

  // Show editor if editing
  if (editingId !== null) {
    return (
      <PromptEditor
        promptId={editingId === "new" ? null : editingId}
        onBack={() => setEditingId(null)}
      />
    )
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle className="text-sm">Prompt 模板</CardTitle>
          <Button size="sm" className="gap-1" onClick={() => setEditingId("new")}>
            <Plus className="h-4 w-4" />
            新建 Prompt
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : prompts && prompts.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>名称</TableHead>
                  <TableHead>分类</TableHead>
                  <TableHead>标签</TableHead>
                  <TableHead className="text-right">使用次数</TableHead>
                  <TableHead className="w-20 text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {prompts.map((p) => (
                  <TableRow
                    key={p.id}
                    className="cursor-pointer"
                    onClick={() => setEditingId(p.id)}
                  >
                    <TableCell>
                      <div>
                        <p className="font-medium text-sm">{p.name}</p>
                        {p.description && (
                          <p className="text-xs text-muted-foreground truncate max-w-xs">
                            {p.description}
                          </p>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="text-xs">
                        {PROMPT_CATEGORIES[p.category] ?? p.category}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {p.tags.slice(0, 3).map((tag) => (
                          <Badge
                            key={tag}
                            variant="outline"
                            className="text-[10px]"
                          >
                            {tag}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {p.usage_count}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7"
                          onClick={(e) => {
                            e.stopPropagation()
                            setEditingId(p.id)
                          }}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-muted-foreground hover:text-destructive"
                          onClick={(e) => {
                            e.stopPropagation()
                            setDeleteTarget({ id: p.id, name: p.name })
                          }}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              <p className="text-sm">暂无 Prompt 模板</p>
              <p className="text-xs mt-1">点击"新建 Prompt"创建第一个模板</p>
            </div>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title={`删除 Prompt — ${deleteTarget?.name ?? ""}`}
        description={`确定要删除 Prompt "${deleteTarget?.name}" 吗？此操作不可撤销。`}
        confirmLabel="删除"
        variant="destructive"
        onConfirm={confirmDelete}
        loading={deleteMutation.isPending}
      />
    </div>
  )
}
