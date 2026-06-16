/** Thread list — lists conversation threads, allows select/delete. */

import { useEffect } from "react"
import { Trash2, MessageSquare } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useChatStore } from "@/stores/chatStore"
import { cn } from "@/lib/utils"

interface ThreadSidebarProps {
  /** When true, renders as a flat list without the outer wrapper/header. */
  embedded?: boolean
  /** Only show threads updated within this many days. */
  maxAgeDays?: number
}

function isWithinDays(dateStr: string, days: number): boolean {
  const date = new Date(dateStr)
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000
  return date.getTime() >= cutoff
}

export function ThreadSidebar({ embedded, maxAgeDays }: ThreadSidebarProps) {
  const {
    threads: allThreads,
    threadsLoading,
    activeThreadId,
    setActiveThread,
    deleteThread,
  } = useChatStore()

  const loadThreads = useChatStore((s) => s.loadThreads)

  useEffect(() => {
    loadThreads()
  }, [loadThreads])

  const threads = maxAgeDays
    ? allThreads.filter((t) => isWithinDays(t.updated_at, maxAgeDays))
    : allThreads

  const listContent = (
    <>
      {threadsLoading && threads.length === 0 ? (
        <div className="px-4 py-8 text-center text-sm text-muted-foreground">
          加载中...
        </div>
      ) : threads.length === 0 ? (
        <div className="px-4 py-4 text-center text-sm text-muted-foreground">
          暂无对话
        </div>
      ) : (
        <div className="space-y-0.5 p-2">
          {threads.length > 0 && (
            <div className="px-2 pb-1 text-xs text-muted-foreground">
              最近对话
            </div>
          )}
          {threads.map((thread) => (
            <div
              key={thread.id}
              className={cn(
                "group flex items-center gap-2 rounded-md px-3 py-2 text-sm cursor-pointer transition-colors",
                activeThreadId === thread.id
                  ? "bg-primary/8 text-primary"
                  : "text-muted-foreground hover:bg-bg-hover hover:text-foreground",
              )}
              onClick={() => setActiveThread(thread.id)}
            >
              <MessageSquare className="h-4 w-4 shrink-0" />
              <span className="flex-1 truncate">{thread.title}</span>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 opacity-0 group-hover:opacity-100 shrink-0"
                onClick={(e) => {
                  e.stopPropagation()
                  deleteThread(thread.id)
                }}
              >
                <Trash2 className="h-3 w-3" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </>
  )

  if (embedded) {
    return listContent
  }

  return (
    <div className="flex h-full w-[280px] flex-col border-r bg-bg-surface">
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <span className="text-sm font-semibold">对话历史</span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {listContent}
      </div>
    </div>
  )
}
