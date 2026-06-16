/** Message list — renders user and agent messages with rich cards, feedback, and retry. */

import React, { useEffect, useMemo, useRef, useState } from "react"
import {
  Bot,
  User,
  ThumbsUp,
  ThumbsDown,
  Copy,
  RotateCcw,
  RefreshCw,
} from "lucide-react"
import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { RichCardDispatcher } from "./RichCardDispatcher"
import type { ChatMessage, IntelCitation } from "@/types/chat"

// ─── Citation rendering helpers ───────────────────────────────────────────────

const CITATION_RE = /\[(\d+)\]/g

function CitationBadge({ index, citation }: { index: number; citation: IntelCitation }) {
  const badge = (
    <span className="inline-flex items-center justify-center h-4 min-w-4 px-0.5 rounded text-[10px] font-medium bg-primary/15 text-primary cursor-pointer align-super hover:bg-primary/25 transition-colors">
      {index}
    </span>
  )

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          {citation.url ? (
            <a href={citation.url} target="_blank" rel="noopener noreferrer" className="no-underline">
              {badge}
            </a>
          ) : (
            badge
          )}
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs p-2.5">
          <p className="text-xs font-medium leading-snug">{citation.title}</p>
          <p className="text-[10px] text-muted-foreground mt-0.5">来源: {citation.source_name}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

function splitByCitations(text: string, citations: IntelCitation[]): React.ReactNode[] {
  const parts: React.ReactNode[] = []
  let lastIndex = 0
  for (const match of text.matchAll(CITATION_RE)) {
    const idx = Number(match[1])
    const citation = citations[idx - 1]
    if (!citation) continue
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }
    parts.push(<CitationBadge key={`c-${match.index}`} index={idx} citation={citation} />)
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }
  return parts
}

function withCitations(children: React.ReactNode, citations: IntelCitation[]): React.ReactNode {
  if (!citations.length) return children
  return React.Children.map(children, (child) => {
    if (typeof child === "string") {
      const parts = splitByCitations(child, citations)
      return parts.length > 1 ? <>{parts}</> : child
    }
    return child
  })
}

// ─── Component types ─────────────────────────────────────────────────────────

interface MessageListProps {
  messages: ChatMessage[]
  loading?: boolean
  threadId?: string | null
  citations?: IntelCitation[]
  onRetry?: (userMessageId: string) => void
  onSubmitFeedback?: (
    messageId: string,
    satisfaction: "satisfied" | "unsatisfied",
    feedback?: string,
  ) => void
  onRegenerateWithFeedback?: (
    assistantMessageId: string,
    feedback: string,
  ) => void
}

/** Inline feedback/actions bar below assistant messages. */
function MessageActions({
  message,
  onSubmitFeedback,
  onRegenerateWithFeedback,
}: {
  message: ChatMessage
  onSubmitFeedback?: MessageListProps["onSubmitFeedback"]
  onRegenerateWithFeedback?: MessageListProps["onRegenerateWithFeedback"]
}) {
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [feedbackText, setFeedbackText] = useState("")

  const satisfaction = message.satisfaction

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content)
    toast.success("已复制到剪贴板")
  }

  const handleThumbsUp = () => {
    onSubmitFeedback?.(message.id, "satisfied")
  }

  const handleThumbsDown = () => {
    if (satisfaction === "unsatisfied") return
    setFeedbackOpen(true)
  }

  const handleSubmitFeedback = () => {
    const text = feedbackText.trim()
    if (!text) return
    onSubmitFeedback?.(message.id, "unsatisfied", text)
    setFeedbackOpen(false)
  }

  const handleRegenerate = () => {
    const text = message.feedback || feedbackText.trim()
    if (!text) return
    onRegenerateWithFeedback?.(message.id, text)
  }

  // Already submitted unsatisfied feedback — show compact state
  if (satisfaction === "unsatisfied") {
    return (
      <div className="flex items-center gap-2 mt-1">
        <span className="text-xs text-muted-foreground flex items-center gap-1">
          <ThumbsDown className="h-3 w-3" />
          已反馈
        </span>
        {message.feedback && (
          <Button
            variant="ghost"
            size="sm"
            className="h-6 text-xs gap-1 px-2"
            onClick={handleRegenerate}
          >
            <RefreshCw className="h-3 w-3" />
            基于反馈重新回答
          </Button>
        )}
      </div>
    )
  }

  // Already satisfied
  if (satisfaction === "satisfied") {
    return (
      <div className="flex items-center gap-2 mt-1">
        <span className="text-xs text-muted-foreground flex items-center gap-1">
          <ThumbsUp className="h-3 w-3" />
          已评价
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={handleCopy}
          title="复制"
        >
          <Copy className="h-3 w-3" />
        </Button>
      </div>
    )
  }

  // Default: show action buttons
  return (
    <div className="mt-1 space-y-2">
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={handleThumbsUp}
          title="满意"
        >
          <ThumbsUp className="h-3 w-3" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={handleThumbsDown}
          title="不满意"
        >
          <ThumbsDown className="h-3 w-3" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={handleCopy}
          title="复制"
        >
          <Copy className="h-3 w-3" />
        </Button>
      </div>

      {/* Feedback textarea — appears on thumbs down */}
      {feedbackOpen && (
        <div className="space-y-1.5">
          <Textarea
            value={feedbackText}
            onChange={(e) => setFeedbackText(e.target.value)}
            placeholder="请描述不满意的原因..."
            className="text-sm resize-none"
            rows={2}
            maxLength={500}
            autoFocus
          />
          <div className="flex gap-1.5">
            <Button
              size="sm"
              className="h-7 text-xs"
              disabled={!feedbackText.trim()}
              onClick={handleSubmitFeedback}
            >
              提交反馈
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              onClick={() => {
                setFeedbackOpen(false)
                setFeedbackText("")
              }}
            >
              取消
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

export function MessageList({
  messages,
  loading = false,
  citations = [],
  onRetry,
  onSubmitFeedback,
  onRegenerateWithFeedback,
}: MessageListProps) {
  const endRef = useRef<HTMLDivElement>(null)

  // Build ReactMarkdown component overrides for citation badges
  const citationComponents = useMemo<Components>(() => {
    if (!citations.length) return {}
    return {
      p: ({ children, node: _n, ...props }) => <p {...props}>{withCitations(children, citations)}</p>,
      li: ({ children, node: _n, ...props }) => <li {...props}>{withCitations(children, citations)}</li>,
      td: ({ children, node: _n, ...props }) => <td {...props}>{withCitations(children, citations)}</td>,
    }
  }, [citations])

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages.length])

  if (messages.length === 0 && !loading) {
    return null
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
      {messages.map((msg, idx) => {
        // Check if next message is an error — used to show retry on user messages
        const nextMsg = messages[idx + 1]
        const showRetry =
          msg.role === "user" && nextMsg?.role === "assistant" && nextMsg._isError

        return (
          <div
            key={msg.id}
            className={cn(
              "flex gap-3 max-w-3xl",
              msg.role === "user" ? "ml-auto flex-row-reverse" : "",
            )}
          >
            {/* Avatar */}
            <div
              className={cn(
                "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
                msg.role === "assistant"
                  ? "bg-accent-primary/10 text-accent-primary"
                  : "bg-muted text-muted-foreground",
              )}
            >
              {msg.role === "assistant" ? (
                <Bot className="h-4 w-4" />
              ) : (
                <User className="h-4 w-4" />
              )}
            </div>

            {/* Content */}
            <div
              className={cn(
                "flex flex-col gap-2 min-w-0",
                msg.role === "user" ? "items-end" : "items-start",
              )}
            >
              <div
                className={cn(
                  "rounded-md px-3 py-2 text-sm leading-relaxed",
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-bg-surface border",
                )}
              >
                {msg.role === "assistant" ? (
                  <div className="prose prose-sm dark:prose-invert max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={citationComponents}>
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                ) : (
                  msg.content
                )}
              </div>

              {/* Rich cards */}
              {msg.rich_cards && msg.rich_cards.length > 0 && (
                <div className="w-full space-y-2">
                  {msg.rich_cards.map((card, i) => (
                    <RichCardDispatcher key={i} card={card} />
                  ))}
                </div>
              )}

              {/* Tool call indicators */}
              {msg.tool_calls && msg.tool_calls.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {msg.tool_calls.map((tc, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground"
                      title={`${tc.tool_name} (${(tc.duration_ms ?? 0).toFixed(0)}ms)`}
                    >
                      {tc.tool_name}
                    </span>
                  ))}
                </div>
              )}

              {/* Assistant message actions (feedback, copy) */}
              {msg.role === "assistant" && !msg._isError && (
                <MessageActions
                  message={msg}
                  onSubmitFeedback={onSubmitFeedback}
                  onRegenerateWithFeedback={onRegenerateWithFeedback}
                />
              )}

              {/* Retry button on user message when next message is an error */}
              {showRetry && onRetry && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs gap-1 mt-1"
                  onClick={() => onRetry(msg.id)}
                >
                  <RotateCcw className="h-3 w-3" />
                  重试
                </Button>
              )}
            </div>
          </div>
        )
      })}

      {/* Loading indicator */}
      {loading && (
        <div className="flex gap-3 max-w-3xl">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent-primary/10 text-accent-primary">
            <Bot className="h-4 w-4" />
          </div>
          <div className="rounded-md border bg-bg-surface px-3 py-2">
            <div className="flex items-center gap-1.5">
              <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground animate-pulse" />
              <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground animate-pulse [animation-delay:150ms]" />
              <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground animate-pulse [animation-delay:300ms]" />
            </div>
          </div>
        </div>
      )}

      <div ref={endRef} />
    </div>
  )
}
