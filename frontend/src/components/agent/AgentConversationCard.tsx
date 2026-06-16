import { useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import {
  BrainCircuit, AlertTriangle, ShieldAlert, Target, ChevronDown, BookOpen,
  Send, MessageCircle, Newspaper, RefreshCw, Clock,
} from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { useAgentConversation } from "@/hooks/useAgentConversation"
import { IntelAttachPopover } from "@/components/agent/IntelAttachPopover"
import type { IntelContext } from "@/api/agent"
import type { DimensionAnalysis, ConversationMessage } from "@/types/agent"

// Signal badge: solid bg at 10% opacity, semantic color
const ACTION_COLORS: Record<string, { text: string; bg: string; border: string }> = {
  buy:    { text: "text-market-up",   bg: "bg-market-up/10",   border: "border-market-up/20" },
  add:    { text: "text-market-up",   bg: "bg-market-up/10",   border: "border-market-up/20" },
  hold:   { text: "text-muted-foreground", bg: "bg-muted",     border: "border-muted-foreground/20" },
  reduce: { text: "text-market-down", bg: "bg-market-down/10", border: "border-market-down/20" },
  sell:   { text: "text-market-down", bg: "bg-market-down/10", border: "border-market-down/20" },
  watch:  { text: "text-primary",     bg: "bg-primary/10",     border: "border-primary/20" },
}

const RISK_BADGE: Record<string, { label: string; variant: "default" | "secondary" | "destructive" }> = {
  low:    { label: "低风险", variant: "secondary" },
  medium: { label: "中风险", variant: "default" },
  high:   { label: "高风险", variant: "destructive" },
}

const SIGNAL_LABELS: Record<string, string> = {
  bullish: "偏多",
  bearish: "偏空",
  neutral: "中性",
}

const SIGNAL_COLORS: Record<string, string> = {
  bullish: "var(--semantic-up)",
  bearish: "var(--semantic-down)",
  neutral: "var(--semantic-flat)",
}

function dimToLink(key: string, symbol: string): string | null {
  if (key === "technical") return `/stock/${symbol}?tab=kline`
  if (key === "capital_flow") return `/stock/${symbol}?tab=kline`
  if (key === "macro") return `/stock/${symbol}?tab=concept`
  return null
}

function confidenceBarColor(pct: number): string {
  if (pct >= 70) return "var(--semantic-up)"
  if (pct >= 40) return "var(--semantic-warning)"
  return "var(--semantic-flat)"
}

interface AgentConversationCardProps {
  symbol: string
  stockName?: string
  position?: { cost_price: number; shares: number; holding_days?: number }
  intelContext?: { item_ids: string[]; analysis_angle?: string; sector?: string }
}

export function AgentConversationCard({ symbol, position, intelContext: externalIntel }: AgentConversationCardProps) {
  const [attachedIntel, setAttachedIntel] = useState<IntelContext | undefined>(undefined)
  const activeIntel = attachedIntel ?? externalIntel
  const { data: conv, isLoading, error, refetch, sendFollowup, isSending, followupError, resetFollowupError } = useAgentConversation(symbol, position, activeIntel)
  const [refsOpen, setRefsOpen] = useState(false)
  const [riskOpen, setRiskOpen] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [input, setInput] = useState("")
  const chatEndRef = useRef<HTMLDivElement>(null)

  const handleAttachIntel = (itemIds: string[]) => {
    setAttachedIntel({ item_ids: itemIds })
  }

  // Auto-scroll chat to bottom
  useEffect(() => {
    if (chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: "smooth" })
    }
  }, [conv?.messages])

  const handleSend = () => {
    const msg = input.trim()
    if (!msg || !conv?.session_id) return
    setInput("")
    sendFollowup({ sessionId: conv.session_id, message: msg })
  }

  const handleSuggestedQuestion = (q: string) => {
    if (!conv?.session_id) return
    setChatOpen(true)
    sendFollowup({ sessionId: conv.session_id, message: q })
  }

  // === Loading ===
  if (isLoading) {
    return (
      <Card className="agent-surface">
        <CardContent className="space-y-4 p-5">
          <div className="flex items-center gap-2.5 text-xs text-muted-foreground py-3">
            <span className="ai-dot" />
            <span className="ai-dot" />
            <span className="ai-dot" />
            <span className="ml-1">正在分析...</span>
          </div>
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-14 w-full" />
        </CardContent>
      </Card>
    )
  }

  // === Data Insufficient ===
  if (conv?.status === "data_insufficient") {
    return (
      <Card className="agent-surface">
        <CardContent className="p-5">
          <div className="text-center py-8 space-y-3">
            <Clock className="h-5 w-5 text-muted-foreground mx-auto" />
            <p className="text-sm text-muted-foreground">
              {conv.message || "数据收集中，请稍后再试"}
            </p>
            <Button variant="outline" size="sm" onClick={() => refetch()} className="gap-1.5">
              <RefreshCw className="h-3.5 w-3.5" />
              重新加载
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  // === Error ===
  if (error || !conv || conv.status === "error") {
    return (
      <Card className="agent-surface">
        <CardContent className="p-5">
          <div className="text-center py-8 space-y-3">
            <AlertTriangle className="h-5 w-5 text-muted-foreground mx-auto" />
            <p className="text-sm text-muted-foreground">
              {conv?.message || "分析暂时不可用，请稍后重试"}
            </p>
            <Button variant="outline" size="sm" onClick={() => refetch()} className="gap-1.5">
              <RefreshCw className="h-3.5 w-3.5" />
              重新分析
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  const unified = conv.analysis
  if (!unified) {
    return (
      <Card className="agent-surface">
        <CardContent className="p-5">
          <div className="text-center py-8">
            <p className="text-sm text-muted-foreground">分析数据不可用</p>
          </div>
        </CardContent>
      </Card>
    )
  }

  const action = unified.action
  const actionLabel = unified.action_label || action
  const actionStyle = ACTION_COLORS[action] ?? ACTION_COLORS.watch
  const riskBadge = RISK_BADGE[unified.risk_level] ?? RISK_BADGE.medium
  const confidencePct = Math.round(unified.confidence.score * 100)
  const barColor = confidenceBarColor(confidencePct)
  const timestamp = unified.generated_at
    ? new Date(unified.generated_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
    : null

  // Separate initial assistant message from followup messages
  const followupMessages = conv.messages.filter(
    (_, i) => i > 0 // skip first assistant message (summary)
  )
  const hasFollowups = followupMessages.length > 0

  return (
    <Card className="agent-surface">
      <CardContent className="p-5 space-y-4">
        {/* ===== Zone A: Header Strip ===== */}
        <div className="flex items-center gap-3">
          <BrainCircuit className="h-4 w-4 shrink-0" style={{ color: "var(--accent-agent)" }} />
          <div className={`rounded-sm px-2.5 py-0.5 text-xs font-semibold ${actionStyle.bg} ${actionStyle.text} border ${actionStyle.border}`}>
            {actionLabel}
          </div>
          <div className="flex items-center gap-2 flex-1">
            <div className="w-20 h-1.5 rounded-[3px] overflow-hidden" style={{ background: "var(--border-subtle)" }}>
              <div
                className="h-full rounded-[3px] transition-all duration-500"
                style={{ width: `${confidencePct}%`, background: barColor }}
              />
            </div>
            <span className="text-xs font-numeric font-semibold w-8">{confidencePct}%</span>
          </div>
          <Badge variant={riskBadge.variant} className="text-[10px]">
            {riskBadge.label}
          </Badge>
          {timestamp && (
            <span className="text-[10px] text-text-tertiary font-numeric">{timestamp}</span>
          )}
        </div>

        {/* Intel context indicator */}
        {activeIntel && activeIntel.item_ids.length > 0 && (
          <div className="flex items-center gap-1.5 text-[10px] text-primary">
            <Newspaper className="h-3 w-3" />
            <span>已注入 {activeIntel.item_ids.length} 条情报上下文</span>
          </div>
        )}

        {/* ===== Zone B: Summary ===== */}
        <div className="prose prose-sm dark:prose-invert max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{unified.summary}</ReactMarkdown>
        </div>

        {/* Target + stop loss */}
        {(unified.target_price || (unified.stop_loss != null && unified.stop_loss > 0)) && (
          <div className="flex gap-4 text-xs text-text-secondary">
            {unified.target_price && (
              <span className="flex items-center gap-1.5">
                <Target className="h-3 w-3" />
                目标价: <span className="font-numeric">{unified.target_price.low.toFixed(2)}~{unified.target_price.high.toFixed(2)}</span>
              </span>
            )}
            {unified.stop_loss != null && unified.stop_loss > 0 && (
              <span className="flex items-center gap-1.5">
                <ShieldAlert className="h-3 w-3" />
                如果跌到 <span className="font-numeric">{unified.stop_loss.toFixed(2)}</span> 元建议卖出
              </span>
            )}
          </div>
        )}

        {/* Confidence basis */}
        {unified.confidence.basis.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {unified.confidence.basis.map((b, i) => (
              <Badge key={i} variant="outline" className="text-[10px] font-normal">
                {b}
              </Badge>
            ))}
          </div>
        )}

        {/* ===== Zone C: Dimension Table ===== */}
        {unified.dimensions.length > 0 && (
          <div className="border-t border-border-subtle pt-4 space-y-1">
            <p className="type-overline text-text-tertiary mb-2">AI 分析维度</p>
            <div className="space-y-0">
              {unified.dimensions.map((dim) => (
                <DimensionRow key={dim.key} dim={dim} symbol={symbol} />
              ))}
            </div>
          </div>
        )}

        {/* ===== Zone D: Evidence & References ===== */}
        {unified.contrarian_check && (
          <div className="border-l-2 border-l-warning pl-3 py-2">
            <p className="text-[11px] font-medium text-warning mb-0.5">反转提醒</p>
            <p className="text-xs text-text-secondary leading-relaxed">{unified.contrarian_check}</p>
          </div>
        )}

        {unified.data_references.length > 0 && (
          <Collapsible open={refsOpen} onOpenChange={setRefsOpen}>
            <CollapsibleTrigger asChild>
              <button className="flex items-center gap-1.5 text-[10px] text-text-tertiary hover:text-text-secondary transition-colors">
                <BookOpen className="h-3 w-3" />
                数据来源 ({unified.data_references.length})
                <ChevronDown className={`h-3 w-3 transition-transform ${refsOpen ? "rotate-180" : ""}`} />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-2">
              <div className="border rounded-sm p-3 space-y-1">
                {unified.data_references.map((ref, i) => (
                  <p key={i} className="text-[10px] text-text-tertiary">
                    <span className="font-medium text-text-secondary">{ref.field}</span>: {ref.value}
                    {ref.source && <span className="text-text-disabled"> ({ref.source})</span>}
                  </p>
                ))}
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}

        {/* ===== Zone E: Risk Warning ===== */}
        {unified.risk_warnings.length > 0 && (
          <Collapsible open={riskOpen} onOpenChange={setRiskOpen}>
            <CollapsibleTrigger asChild>
              <button className="flex items-center gap-1.5 text-[11px] text-warning font-medium">
                <AlertTriangle className="h-3 w-3" />
                风险提示 ({unified.risk_warnings.length})
                <ChevronDown className={`h-3 w-3 transition-transform ${riskOpen ? "rotate-180" : ""}`} />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-1.5">
              <div className="border-l-2 border-l-warning pl-3 space-y-1">
                {unified.risk_warnings.map((w, i) => (
                  <p key={i} className="text-xs text-text-secondary leading-relaxed">{w.description}</p>
                ))}
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}

        {/* ===== Zone G: Conversation ===== */}
        <div className="border-t border-border-subtle pt-4 space-y-3">
          {/* Suggested questions (chips) */}
          {conv.suggested_questions.length > 0 && !hasFollowups && (
            <div className="flex flex-wrap gap-2">
              {conv.suggested_questions.map((q, i) => (
                <button
                  key={i}
                  className="rounded-md border border-border-default bg-bg-surface px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
                  onClick={() => handleSuggestedQuestion(q)}
                  disabled={isSending}
                >
                  {q}
                </button>
              ))}
            </div>
          )}

          {/* Chat history (collapsed by default, expand on first followup) */}
          {(hasFollowups || chatOpen) && (
            <div className="space-y-3">
              {/* Messages */}
              <div className="max-h-80 overflow-y-auto space-y-2.5 pr-1">
                {followupMessages.map((msg, i) => (
                  <ChatBubble key={i} message={msg} />
                ))}
                {isSending && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
                    <span className="ai-dot" />
                    <span className="ai-dot" />
                    <span className="ai-dot" />
                    <span className="ml-1">思考中...</span>
                  </div>
                )}
                {followupError && !isSending && (
                  <div className="flex items-center gap-2 text-xs text-warning py-1">
                    <AlertTriangle className="h-3 w-3 shrink-0" />
                    <span>回复失败，请重试</span>
                    <button
                      className="text-primary hover:underline ml-1"
                      onClick={() => resetFollowupError()}
                    >
                      清除
                    </button>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>
            </div>
          )}

          {/* Input area */}
          <div className="flex items-center gap-2">
            {!chatOpen && !hasFollowups && (
              <>
                <button
                  className="flex items-center gap-1.5 text-xs text-text-tertiary hover:text-text-secondary transition-colors"
                  onClick={() => setChatOpen(true)}
                >
                  <MessageCircle className="h-3.5 w-3.5" />
                  追问
                </button>
                <IntelAttachPopover symbol={symbol} onAttach={handleAttachIntel} />
              </>
            )}
            {(chatOpen || hasFollowups) && (
              <div className="flex items-center gap-2 w-full">
                <input
                  type="text"
                  className="flex-1 rounded-md border border-border-default bg-bg-surface px-3 py-1.5 text-sm text-text-primary placeholder:text-text-disabled outline-none focus:border-primary transition-colors"
                  placeholder="继续追问..."
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault()
                      handleSend()
                    }
                  }}
                  disabled={isSending}
                />
                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 w-8 p-0 shrink-0"
                  onClick={handleSend}
                  disabled={isSending || !input.trim()}
                >
                  <Send className="h-3.5 w-3.5" />
                </Button>
              </div>
            )}
          </div>
        </div>

        {/* ===== Engine info ===== */}
        {unified.model_used && (
          <div className="flex items-center gap-3 text-[10px] text-text-disabled">
            <span>{unified.model_used}</span>
            {unified.generated_at && <span>{new Date(unified.generated_at).toLocaleString("zh-CN")}</span>}
          </div>
        )}

        {/* ===== Zone F: Disclaimer ===== */}
        <p className="text-[11px] text-text-tertiary leading-relaxed border-t border-border-subtle pt-3">
          {unified.disclaimer || conv.disclaimer || "以上分析由 AI 模型生成，仅供参考，不构成投资建议。股市有风险，投资需谨慎。"}
        </p>
      </CardContent>
    </Card>
  )
}

/** Chat bubble component */
function ChatBubble({ message }: { message: ConversationMessage }) {
  const isUser = message.role === "user"
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-md px-3 py-2 text-xs leading-relaxed ${
          isUser
            ? "bg-primary/10 text-text-primary"
            : "bg-bg-surface border border-border-subtle text-text-secondary"
        }`}
      >
        {isUser ? (
          <span className="whitespace-pre-wrap">{message.content}</span>
        ) : (
          <div className="prose prose-sm dark:prose-invert max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  )
}

/** Dimension row — inline table row format */
function DimensionRow({ dim, symbol }: { dim: DimensionAnalysis; symbol: string }) {
  const [expanded, setExpanded] = useState(false)
  const pct = Math.round(dim.score * 100)
  const color = SIGNAL_COLORS[dim.signal] ?? SIGNAL_COLORS.neutral
  const link = dimToLink(dim.key, symbol)

  return (
    <div className="py-2 border-b border-border-subtle last:border-b-0">
      <div
        className="flex items-center gap-3 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="text-xs font-medium w-16 shrink-0">{dim.label}</span>
        <span className="text-xs w-12 shrink-0" style={{ color }}>
          {SIGNAL_LABELS[dim.signal] ?? dim.signal}
        </span>
        <div className="w-20 h-1.5 rounded-[3px] overflow-hidden shrink-0" style={{ background: "var(--border-subtle)" }}>
          <div
            className="h-full rounded-[3px]"
            style={{ width: `${pct}%`, backgroundColor: color }}
          />
        </div>
        <span className="text-[10px] font-numeric text-text-tertiary w-7">{pct}%</span>
        <span className="flex-1" />
        <ChevronDown className={`h-3 w-3 text-text-disabled transition-transform ${expanded ? "rotate-180" : ""}`} />
      </div>
      {expanded && (
        <div className="mt-1.5 ml-16 space-y-1">
          <div className="text-xs text-text-secondary leading-relaxed prose prose-sm dark:prose-invert max-w-none prose-p:my-0">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{dim.reasoning}</ReactMarkdown>
          </div>
          {link && (
            <Link to={link} className="text-xs text-primary hover:underline">
              查看详情 &rarr;
            </Link>
          )}
        </div>
      )}
    </div>
  )
}
