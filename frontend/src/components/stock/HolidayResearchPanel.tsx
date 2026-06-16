import { useState, useRef, useEffect } from "react"
import { formatTime, formatDateTime } from "@/lib/formatters"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import {
  CalendarOff,
  ChevronDown,
  ChevronRight,
  Loader2,
  MessageSquare,
  Brain,
  Send,
  Trash2,
  Plus,
  ArrowUp,
  ArrowDown,
  Minus,
  AlertTriangle,
  Target,
  CheckCircle2,
  Network,
  ClipboardList,
  GitBranch,
  Lightbulb,
  Link2,
  ThumbsUp,
  ThumbsDown,
  CircleDot,
  Pencil,
  X,
  RotateCcw,
  Save,
  Maximize2,
} from "lucide-react"
import { toast } from "sonner"
import {
  useResearchContext,
  useAddNote,
  useDeleteNote,
  useEvidence,
  useAddEvidence,
  useDeleteEvidence,
  useGenerateQuestions,
  useScenarioAnalysis,
  useComprehensiveAnalysis,
  useFollowupQuestion,
  useConversation,
  useClearConversation,
  useProfileOverrides,
  useUpdateProfileOverrides,
  useDeleteProfileOverrides,
  useAvailableIndustries,
} from "@/hooks/useHolidayResearch"
import type {
  AssociationProfile,
  ResearchQuestion,
  ResearchChecklist,
  EvidenceItem,
  ScenarioResult,
  ScenarioAnalysisResult,
  ComprehensiveAnalysisResult,
  FollowupResponse,
  ConversationMessage,
  ProfileOverride,
  IndustryOption,
} from "@/types/holiday-research"

interface HolidayResearchPanelProps {
  symbol: string
  stockName?: string
  hasPosition?: boolean
}

const NOTE_TYPES = [
  { value: "observation", label: "观察" },
  { value: "box_office", label: "票房" },
  { value: "industry_report", label: "行业" },
  { value: "policy", label: "政策" },
  { value: "custom", label: "其他" },
] as const

const NOTE_TYPE_COLORS: Record<string, string> = {
  observation: "bg-info/10 text-info",
  box_office: "bg-warning/10 text-warning",
  industry_report: "bg-accent-primary/10 text-accent-primary",
  policy: "bg-danger/10 text-danger",
  custom: "bg-muted text-muted-foreground",
}

const IMPACT_CONFIG = {
  positive: { icon: ArrowUp, color: "text-market-up", bg: "bg-market-up/10" },
  negative: { icon: ArrowDown, color: "text-market-down", bg: "bg-market-down/10" },
  neutral: { icon: Minus, color: "text-muted-foreground", bg: "bg-muted" },
}

const EVIDENCE_IMPACT = {
  bullish: { icon: ThumbsUp, color: "text-market-up", label: "利多" },
  bearish: { icon: ThumbsDown, color: "text-market-down", label: "利空" },
  neutral: { icon: CircleDot, color: "text-muted-foreground", label: "中性" },
}

const PROBABILITY_COLORS: Record<string, string> = {
  low: "bg-info/20 text-info",
  medium: "bg-warning/20 text-warning",
  high: "bg-danger/20 text-danger",
}

const RESONANCE_COLORS: Record<string, string> = {
  strong: "bg-danger/20 text-danger",
  moderate: "bg-warning/20 text-warning",
  weak: "bg-info/20 text-info",
  none: "bg-muted text-muted-foreground",
}

const CATEGORY_LABELS: Record<string, string> = {
  industry_event: "行业事件",
  competitor: "竞争对手",
  policy: "政策",
  macro: "宏观",
  cross_market: "跨市场",
  supply_chain: "供应链",
}

const ACTION_LABELS: Record<string, { label: string; color: string }> = {
  buy: { label: "买入", color: "bg-market-up text-white" },
  add: { label: "加仓", color: "bg-market-up/80 text-white" },
  hold: { label: "持有", color: "bg-info text-white" },
  reduce: { label: "减仓", color: "bg-market-down/80 text-white" },
  sell: { label: "卖出", color: "bg-market-down text-white" },
  watch: { label: "观望", color: "bg-muted-foreground text-white" },
}

const DIRECTION_LABELS: Record<string, { label: string; color: string }> = {
  up: { label: "上涨", color: "text-market-up" },
  down: { label: "下跌", color: "text-market-down" },
  flat: { label: "横盘", color: "text-muted-foreground" },
}

export function HolidayResearchPanel({ symbol, stockName, hasPosition }: HolidayResearchPanelProps) {
  const [enabled, setEnabled] = useState(false)
  const [noteText, setNoteText] = useState("")
  const [noteType, setNoteType] = useState("observation")
  const [checklist, setChecklist] = useState<ResearchChecklist | null>(null)
  const [scenarioResult, setScenarioResult] = useState<ScenarioAnalysisResult | null>(null)
  const [analysisResult, setAnalysisResult] = useState<ComprehensiveAnalysisResult | null>(null)
  const [qaHistory, setQaHistory] = useState<FollowupResponse[]>([])
  const [questionText, setQuestionText] = useState("")
  // Evidence add form state
  const [evidenceForm, setEvidenceForm] = useState<{
    questionId: string
    content: string
    impact: string
    confidence: string
    source: string
    evidenceType: string
  } | null>(null)

  const { data: context, isLoading: loadingContext } = useResearchContext(symbol, enabled)
  const { data: evidenceList } = useEvidence(symbol, enabled)
  const { data: overrideData } = useProfileOverrides(symbol, enabled)
  const updateOverrideMutation = useUpdateProfileOverrides(symbol)
  const deleteOverrideMutation = useDeleteProfileOverrides(symbol)
  const { data: availableIndustries } = useAvailableIndustries(enabled)
  const addNoteMutation = useAddNote(symbol)
  const deleteNoteMutation = useDeleteNote(symbol)
  const addEvidenceMutation = useAddEvidence(symbol)
  const deleteEvidenceMutation = useDeleteEvidence(symbol)
  const questionsMutation = useGenerateQuestions(symbol)
  const scenarioMutation = useScenarioAnalysis(symbol)
  const analysisMutation = useComprehensiveAnalysis(symbol)
  const followupMutation = useFollowupQuestion(symbol)

  // Not enabled yet — show teaser
  if (!enabled) {
    return (
      <Card className="border-warning/30">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <CalendarOff className="h-4 w-4 text-warning" />
            假期研究工作台
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-4 space-y-2">
            <p className="text-xs text-muted-foreground">
              综合关联画像 + 研究清单 + 情景分析 + AI 深度研判，<br />
              帮助做出假期后科学的操作决策
            </p>
            <Button size="sm" onClick={() => setEnabled(true)}>
              <CalendarOff className="h-3.5 w-3.5 mr-1.5" />
              开启研究工作台
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  // Loading context
  if (loadingContext && !context) {
    return (
      <Card className="border-warning/30">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <CalendarOff className="h-4 w-4 text-warning" />
            假期研究工作台
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            正在采集研究数据...
          </div>
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-16 w-full" />
        </CardContent>
      </Card>
    )
  }

  const handleAddNote = () => {
    if (!noteText.trim()) return
    addNoteMutation.mutate(
      { content: noteText.trim(), noteType },
      {
        onSuccess: () => {
          setNoteText("")
          toast.success("笔记已添加")
        },
        onError: () => toast.error("添加失败"),
      },
    )
  }

  const handleDeleteNote = (noteId: string) => {
    deleteNoteMutation.mutate(noteId, {
      onSuccess: () => toast.success("笔记已删除"),
      onError: () => toast.error("删除失败"),
    })
  }

  const handleAddEvidence = () => {
    if (!evidenceForm || !evidenceForm.content.trim()) return
    addEvidenceMutation.mutate(
      {
        content: evidenceForm.content.trim(),
        evidence_type: evidenceForm.evidenceType,
        linked_question_id: evidenceForm.questionId,
        impact: evidenceForm.impact,
        confidence: evidenceForm.confidence,
        source: evidenceForm.source,
      },
      {
        onSuccess: () => {
          setEvidenceForm(null)
          toast.success("证据已添加")
        },
        onError: () => toast.error("添加失败"),
      },
    )
  }

  const handleDeleteEvidence = (evidenceId: string) => {
    deleteEvidenceMutation.mutate(evidenceId, {
      onSuccess: () => toast.success("证据已删除"),
      onError: () => toast.error("删除失败"),
    })
  }

  const handleGenerateQuestions = () => {
    questionsMutation.mutate(undefined, {
      onSuccess: (data) => {
        setChecklist(data)
        if (data.status === "error") toast.error("研究清单生成失败")
      },
      onError: () => toast.error("研究清单请求失败"),
    })
  }

  const handleAnalyzeScenarios = () => {
    scenarioMutation.mutate(undefined, {
      onSuccess: (data) => {
        setScenarioResult(data)
        if (data.status === "error") toast.error("情景分析失败")
      },
      onError: () => toast.error("情景分析请求失败"),
    })
  }

  const handleAnalyze = () => {
    analysisMutation.mutate(undefined, {
      onSuccess: (data) => {
        setAnalysisResult(data)
        if (data.status === "error") toast.error("分析生成失败")
      },
      onError: () => toast.error("分析请求失败"),
    })
  }

  const handleAsk = () => {
    if (!questionText.trim()) return
    const q = questionText.trim()
    setQuestionText("")
    followupMutation.mutate(q, {
      onSuccess: (data) => setQaHistory((prev) => [...prev, data]),
      onError: () => toast.error("追问请求失败"),
    })
  }

  const profile = context?.association_profile ?? null
  const userNotes = context?.user_notes ?? []
  const calInfo = context?.calendar_info ?? {}
  const evidence = evidenceList ?? []

  return (
    <Card className="border-warning/30">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <CalendarOff className="h-4 w-4 text-warning" />
            假期研究工作台
          </CardTitle>
          <div className="flex items-center gap-2">
            {calInfo.next_trading_day && (
              <Badge variant="outline" className="text-[10px]">
                下一交易日: {calInfo.next_trading_day}
              </Badge>
            )}
            {hasPosition && (
              <Badge variant="secondary" className="text-[10px]">持仓中</Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">

        {/* === Section 1: Association Summary === */}
        <AssociationSummarySection
          profile={profile}
          overrideData={overrideData ?? null}
          availableIndustries={availableIndustries ?? []}
          onSaveOverride={(body) => {
            updateOverrideMutation.mutate(body, {
              onSuccess: () => toast.success("关联画像已自定义"),
              onError: () => toast.error("保存失败"),
            })
          }}
          onResetOverride={() => {
            deleteOverrideMutation.mutate(undefined, {
              onSuccess: () => toast.success("已重置为自动关联"),
              onError: () => toast.error("重置失败"),
            })
          }}
          isSaving={updateOverrideMutation.isPending || deleteOverrideMutation.isPending}
        />

        <div className="border-t" />

        {/* === Section 2: Research Checklist === */}
        <ResearchChecklistSection
          checklist={checklist}
          evidence={evidence}
          userNotes={userNotes}
          noteText={noteText}
          noteType={noteType}
          evidenceForm={evidenceForm}
          onNoteTextChange={setNoteText}
          onNoteTypeChange={setNoteType}
          onAddNote={handleAddNote}
          onDeleteNote={handleDeleteNote}
          onEvidenceFormChange={setEvidenceForm}
          onAddEvidence={handleAddEvidence}
          onDeleteEvidence={handleDeleteEvidence}
          onGenerate={handleGenerateQuestions}
          isAddingNote={addNoteMutation.isPending}
          isDeletingNote={deleteNoteMutation.isPending}
          isAddingEvidence={addEvidenceMutation.isPending}
          isGenerating={questionsMutation.isPending}
        />

        <div className="border-t" />

        {/* === Section 3: Scenario Sandbox === */}
        <ScenarioSandboxSection
          scenarioResult={scenarioResult}
          onAnalyze={handleAnalyzeScenarios}
          isAnalyzing={scenarioMutation.isPending}
        />

        <div className="border-t" />

        {/* === Section 4: AI Comprehensive Analysis === */}
        <ComprehensiveAnalysisSection
          result={analysisResult}
          onAnalyze={handleAnalyze}
          isAnalyzing={analysisMutation.isPending}
        />

        <div className="border-t" />

        {/* === Section 5: Follow-up Q&A === */}
        <FollowupSection
          symbol={symbol}
          stockName={stockName ?? ""}
          profile={profile}
          qaHistory={qaHistory}
          questionText={questionText}
          onQuestionTextChange={setQuestionText}
          onAsk={handleAsk}
          isAsking={followupMutation.isPending}
        />

        {/* Disclaimer */}
        <p className="text-[10px] text-muted-foreground/60 border-t pt-2">
          AI 分析仅供参考，不构成投资建议。股市有风险，投资需谨慎。
        </p>
      </CardContent>
    </Card>
  )
}


// ─── Section 1: Association Summary ─────────────────────────────────

interface AssociationSummaryProps {
  profile: AssociationProfile | null
  overrideData: ProfileOverride | null
  availableIndustries: IndustryOption[]
  onSaveOverride: (body: import("@/types/holiday-research").ProfileOverrideRequest) => void
  onResetOverride: () => void
  isSaving: boolean
}

function AssociationSummarySection({
  profile,
  overrideData,
  availableIndustries,
  onSaveOverride,
  onResetOverride,
  isSaving,
}: AssociationSummaryProps) {
  const [open, setOpen] = useState(true)
  const [editing, setEditing] = useState(false)
  // Edit form state
  const [removedConcepts, setRemovedConcepts] = useState<Set<string>>(new Set())
  const [addedConceptName, setAddedConceptName] = useState("")
  const [removedPeers, setRemovedPeers] = useState<Set<string>>(new Set())
  const [addedPeerSymbol, setAddedPeerSymbol] = useState("")
  const [addedPeerMarket, setAddedPeerMarket] = useState("us")
  const [removedKeywords, setRemovedKeywords] = useState<Set<string>>(new Set())
  const [addedKeyword, setAddedKeyword] = useState("")
  const [industryOverride, setIndustryOverride] = useState<string | null>(null)
  // Track new items added during this edit session
  const [newConcepts, setNewConcepts] = useState<Array<{ code: string; name: string }>>([])
  const [newPeers, setNewPeers] = useState<Array<{ symbol: string; market: string; tags: string[] }>>([])
  const [newKeywords, setNewKeywords] = useState<string[]>([])

  if (!profile) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-1.5 text-xs font-medium">
          <Network className="h-3.5 w-3.5" />
          关联画像
        </div>
        <p className="text-xs text-muted-foreground text-center py-2">关联画像加载中...</p>
      </div>
    )
  }

  const ip = profile.industry_profile
  const hasOverride = overrideData?.has_override ?? false

  const enterEdit = () => {
    setEditing(true)
    setRemovedConcepts(new Set())
    setRemovedPeers(new Set())
    setRemovedKeywords(new Set())
    setNewConcepts([])
    setNewPeers([])
    setNewKeywords([])
    setIndustryOverride(null)
  }

  const cancelEdit = () => setEditing(false)

  const handleSave = () => {
    const body: import("@/types/holiday-research").ProfileOverrideRequest = {}
    // Merge existing override with edits
    const existingAddedConcepts = overrideData?.added_concepts ?? []
    const existingRemovedCodes = overrideData?.removed_concept_codes ?? []
    const existingAddedPeers = overrideData?.added_peers ?? []
    const existingRemovedPeerSymbols = overrideData?.removed_peer_symbols ?? []
    const existingAddedKeywords = overrideData?.added_keywords ?? []
    const existingRemovedKeywords = overrideData?.removed_keywords ?? []

    body.added_concepts = [...existingAddedConcepts, ...newConcepts]
    body.removed_concept_codes = [...new Set([...existingRemovedCodes, ...removedConcepts])]
    body.added_peers = [...existingAddedPeers, ...newPeers]
    body.removed_peer_symbols = [...new Set([...existingRemovedPeerSymbols, ...removedPeers])]
    body.added_keywords = [...new Set([...existingAddedKeywords, ...newKeywords])]
    body.removed_keywords = [...new Set([...existingRemovedKeywords, ...removedKeywords])]
    if (industryOverride !== null) body.industry_override = industryOverride
    else if (overrideData?.industry_override) body.industry_override = overrideData.industry_override

    onSaveOverride(body)
    setEditing(false)
  }

  return (
    <div className="space-y-2">
      <Collapsible open={open} onOpenChange={setOpen}>
        <div className="flex items-center justify-between">
          <CollapsibleTrigger className="flex items-center gap-1.5 text-xs font-medium hover:text-foreground text-muted-foreground transition-colors">
            {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            <Network className="h-3.5 w-3.5" />
            关联画像
            <Badge className={`text-[8px] px-1 py-0 ml-1 ${RESONANCE_COLORS[profile.resonance_level] ?? RESONANCE_COLORS.none}`}>
              共振: {profile.resonance_level}
            </Badge>
            {ip && (
              <Badge variant="outline" className="text-[8px] px-1 py-0">
                {ip.display}
              </Badge>
            )}
            {hasOverride && (
              <Badge variant="secondary" className="text-[8px] px-1 py-0 bg-warning/10 text-warning">
                已自定义
              </Badge>
            )}
          </CollapsibleTrigger>
          <div className="flex items-center gap-1">
            {!editing ? (
              <Button variant="ghost" size="icon" className="h-5 w-5" onClick={enterEdit} title="编辑关联画像">
                <Pencil className="h-3 w-3" />
              </Button>
            ) : (
              <>
                <Button variant="ghost" size="icon" className="h-5 w-5" onClick={cancelEdit} title="取消">
                  <X className="h-3 w-3" />
                </Button>
                {hasOverride && (
                  <Button variant="ghost" size="icon" className="h-5 w-5 text-warning" onClick={() => { onResetOverride(); setEditing(false) }} disabled={isSaving} title="重置为自动">
                    <RotateCcw className="h-3 w-3" />
                  </Button>
                )}
                <Button variant="ghost" size="icon" className="h-5 w-5 text-info" onClick={handleSave} disabled={isSaving} title="保存">
                  <Save className="h-3 w-3" />
                </Button>
              </>
            )}
          </div>
        </div>
        <CollapsibleContent className="mt-2 space-y-2.5">
          {/* Industry override (edit mode) */}
          {editing && availableIndustries.length > 0 && (
            <div className="space-y-1">
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">行业标签</p>
              <Select value={industryOverride ?? ip?.tag ?? ""} onValueChange={(v) => setIndustryOverride(v)}>
                <SelectTrigger className="h-7 text-xs w-48">
                  <SelectValue placeholder="选择行业" />
                </SelectTrigger>
                <SelectContent>
                  {availableIndustries.map((ind) => (
                    <SelectItem key={ind.tag} value={ind.tag} className="text-xs">
                      {ind.display} ({ind.tag})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Concepts */}
          {(profile.concepts.length > 0 || newConcepts.length > 0) && (
            <div className="space-y-1">
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">概念板块</p>
              <div className="flex flex-wrap gap-1.5">
                {profile.concepts.filter((c) => !removedConcepts.has(c.code)).map((c, i) => (
                  <div key={i} className="flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs">
                    <span className="font-medium">{c.name}</span>
                    <span className={c.pct_change >= 0 ? "text-market-up font-mono" : "text-market-down font-mono"}>
                      {c.pct_change >= 0 ? "+" : ""}{c.pct_change.toFixed(2)}%
                    </span>
                    {c.rank_pct != null && (
                      <span className="text-[9px] text-muted-foreground">
                        Top{Math.round(c.rank_pct * 100)}%
                      </span>
                    )}
                    {editing && (
                      <button onClick={() => setRemovedConcepts((s) => new Set(s).add(c.code))} className="ml-0.5 text-muted-foreground hover:text-danger">
                        <X className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                ))}
                {newConcepts.map((c, i) => (
                  <div key={`new-${i}`} className="flex items-center gap-1 rounded-md border border-warning/50 px-2 py-0.5 text-xs bg-warning/5">
                    <span className="font-medium">{c.name}</span>
                    <button onClick={() => setNewConcepts((prev) => prev.filter((_, j) => j !== i))} className="ml-0.5 text-muted-foreground hover:text-danger">
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
              {editing && (
                <div className="flex gap-1 mt-1">
                  <Input className="h-6 text-xs flex-1" placeholder="概念名称" value={addedConceptName} onChange={(e) => setAddedConceptName(e.target.value)} />
                  <Button size="sm" variant="outline" className="h-6 text-[10px] px-2" onClick={() => {
                    if (addedConceptName.trim()) {
                      setNewConcepts((prev) => [...prev, { code: `USER_${Date.now()}`, name: addedConceptName.trim() }])
                      setAddedConceptName("")
                    }
                  }}>
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
              )}
            </div>
          )}

          {/* Cross-market peers */}
          {(profile.cross_market_peers.length > 0 || newPeers.length > 0) && (
            <div className="space-y-1">
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">跨市场同行</p>
              <div className="flex flex-wrap gap-1.5">
                {profile.cross_market_peers.filter((p) => !removedPeers.has(p.symbol)).map((p, i) => (
                  <div key={i} className="flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs">
                    <Badge variant="outline" className="text-[8px] px-1 py-0">
                      {p.market.toUpperCase()}
                    </Badge>
                    <span>{p.symbol}</span>
                    {editing && (
                      <button onClick={() => setRemovedPeers((s) => new Set(s).add(p.symbol))} className="ml-0.5 text-muted-foreground hover:text-danger">
                        <X className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                ))}
                {newPeers.map((p, i) => (
                  <div key={`new-${i}`} className="flex items-center gap-1 rounded-md border border-warning/50 px-2 py-0.5 text-xs bg-warning/5">
                    <Badge variant="outline" className="text-[8px] px-1 py-0">{p.market.toUpperCase()}</Badge>
                    <span>{p.symbol}</span>
                    <button onClick={() => setNewPeers((prev) => prev.filter((_, j) => j !== i))} className="ml-0.5 text-muted-foreground hover:text-danger">
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
              {editing && (
                <div className="flex gap-1 mt-1">
                  <Input className="h-6 text-xs flex-1" placeholder="代码 (如 AAPL)" value={addedPeerSymbol} onChange={(e) => setAddedPeerSymbol(e.target.value)} />
                  <Select value={addedPeerMarket} onValueChange={setAddedPeerMarket}>
                    <SelectTrigger className="h-6 text-xs w-20">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="us" className="text-xs">US</SelectItem>
                      <SelectItem value="hk" className="text-xs">HK</SelectItem>
                      <SelectItem value="commodity" className="text-xs">商品</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button size="sm" variant="outline" className="h-6 text-[10px] px-2" onClick={() => {
                    if (addedPeerSymbol.trim()) {
                      setNewPeers((prev) => [...prev, { symbol: addedPeerSymbol.trim().toUpperCase(), market: addedPeerMarket, tags: [] }])
                      setAddedPeerSymbol("")
                    }
                  }}>
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
              )}
            </div>
          )}

          {/* Industry profile */}
          {ip && !editing && (
            <div className="space-y-1">
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">行业画像: {ip.display}</p>
              <div className="grid grid-cols-2 gap-2">
                {ip.key_metrics.length > 0 && (
                  <div>
                    <p className="text-[9px] text-muted-foreground">关键指标</p>
                    <div className="flex flex-wrap gap-1 mt-0.5">
                      {ip.key_metrics.map((m, i) => (
                        <Badge key={i} variant="secondary" className="text-[9px]">{m}</Badge>
                      ))}
                    </div>
                  </div>
                )}
                {ip.value_chain.length > 0 && (
                  <div>
                    <p className="text-[9px] text-muted-foreground">产业链</p>
                    <p className="text-[10px] mt-0.5">{ip.value_chain.join(" → ")}</p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Keyword themes */}
          {(profile.keyword_themes.length > 0 || newKeywords.length > 0) && (
            <div className="space-y-1">
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">关键词主题</p>
              <div className="flex flex-wrap gap-1">
                {profile.keyword_themes.filter((kw) => !removedKeywords.has(kw)).map((kw, i) => (
                  <div key={i} className="flex items-center gap-0.5">
                    <Badge variant="outline" className="text-[9px]">{kw}</Badge>
                    {editing && (
                      <button onClick={() => setRemovedKeywords((s) => new Set(s).add(kw))} className="text-muted-foreground hover:text-danger">
                        <X className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                ))}
                {newKeywords.map((kw, i) => (
                  <div key={`new-${i}`} className="flex items-center gap-0.5">
                    <Badge variant="outline" className="text-[9px] border-warning/50 bg-warning/5">{kw}</Badge>
                    <button onClick={() => setNewKeywords((prev) => prev.filter((_, j) => j !== i))} className="text-muted-foreground hover:text-danger">
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
              {editing && (
                <div className="flex gap-1 mt-1">
                  <Input className="h-6 text-xs flex-1" placeholder="关键词" value={addedKeyword} onChange={(e) => setAddedKeyword(e.target.value)} />
                  <Button size="sm" variant="outline" className="h-6 text-[10px] px-2" onClick={() => {
                    if (addedKeyword.trim()) {
                      setNewKeywords((prev) => [...prev, addedKeyword.trim()])
                      setAddedKeyword("")
                    }
                  }}>
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
              )}
            </div>
          )}

          {/* Edit mode: empty state addable sections */}
          {editing && profile.concepts.length === 0 && newConcepts.length === 0 && (
            <div className="space-y-1">
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">概念板块</p>
              <div className="flex gap-1">
                <Input className="h-6 text-xs flex-1" placeholder="概念名称" value={addedConceptName} onChange={(e) => setAddedConceptName(e.target.value)} />
                <Button size="sm" variant="outline" className="h-6 text-[10px] px-2" onClick={() => {
                  if (addedConceptName.trim()) {
                    setNewConcepts((prev) => [...prev, { code: `USER_${Date.now()}`, name: addedConceptName.trim() }])
                    setAddedConceptName("")
                  }
                }}>
                  <Plus className="h-3 w-3" />
                </Button>
              </div>
            </div>
          )}
          {editing && profile.cross_market_peers.length === 0 && newPeers.length === 0 && (
            <div className="space-y-1">
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">跨市场同行</p>
              <div className="flex gap-1">
                <Input className="h-6 text-xs flex-1" placeholder="代码 (如 AAPL)" value={addedPeerSymbol} onChange={(e) => setAddedPeerSymbol(e.target.value)} />
                <Select value={addedPeerMarket} onValueChange={setAddedPeerMarket}>
                  <SelectTrigger className="h-6 text-xs w-20">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="us" className="text-xs">US</SelectItem>
                    <SelectItem value="hk" className="text-xs">HK</SelectItem>
                    <SelectItem value="commodity" className="text-xs">商品</SelectItem>
                  </SelectContent>
                </Select>
                <Button size="sm" variant="outline" className="h-6 text-[10px] px-2" onClick={() => {
                  if (addedPeerSymbol.trim()) {
                    setNewPeers((prev) => [...prev, { symbol: addedPeerSymbol.trim().toUpperCase(), market: addedPeerMarket, tags: [] }])
                    setAddedPeerSymbol("")
                  }
                }}>
                  <Plus className="h-3 w-3" />
                </Button>
              </div>
            </div>
          )}
          {editing && profile.keyword_themes.length === 0 && newKeywords.length === 0 && (
            <div className="space-y-1">
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">关键词主题</p>
              <div className="flex gap-1">
                <Input className="h-6 text-xs flex-1" placeholder="关键词" value={addedKeyword} onChange={(e) => setAddedKeyword(e.target.value)} />
                <Button size="sm" variant="outline" className="h-6 text-[10px] px-2" onClick={() => {
                  if (addedKeyword.trim()) {
                    setNewKeywords((prev) => [...prev, addedKeyword.trim()])
                    setAddedKeyword("")
                  }
                }}>
                  <Plus className="h-3 w-3" />
                </Button>
              </div>
            </div>
          )}
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}


// ─── Section 2: Research Checklist ──────────────────────────────────

interface ChecklistSectionProps {
  checklist: ResearchChecklist | null
  evidence: EvidenceItem[]
  userNotes: Array<{ id: string; content: string; note_type: string; created_at: string }>
  noteText: string
  noteType: string
  evidenceForm: {
    questionId: string
    content: string
    impact: string
    confidence: string
    source: string
    evidenceType: string
  } | null
  onNoteTextChange: (v: string) => void
  onNoteTypeChange: (v: string) => void
  onAddNote: () => void
  onDeleteNote: (id: string) => void
  onEvidenceFormChange: (v: ChecklistSectionProps["evidenceForm"]) => void
  onAddEvidence: () => void
  onDeleteEvidence: (id: string) => void
  onGenerate: () => void
  isAddingNote: boolean
  isDeletingNote: boolean
  isAddingEvidence: boolean
  isGenerating: boolean
}

function ResearchChecklistSection({
  checklist,
  evidence,
  userNotes,
  noteText,
  noteType,
  evidenceForm,
  onNoteTextChange,
  onNoteTypeChange,
  onAddNote,
  onDeleteNote,
  onEvidenceFormChange,
  onAddEvidence,
  onDeleteEvidence,
  onGenerate,
  isAddingNote,
  isDeletingNote,
  isAddingEvidence,
  isGenerating,
}: ChecklistSectionProps) {
  const [notesOpen, setNotesOpen] = useState(false)

  const questions = checklist?.questions ?? []
  const answeredCount = questions.filter(
    (q) => evidence.some((e) => e.linked_question_id === q.id),
  ).length

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-medium">
          <ClipboardList className="h-3.5 w-3.5" />
          研究清单
          {questions.length > 0 && (
            <span className="text-[10px] text-muted-foreground">
              ({answeredCount}/{questions.length} 已收集证据)
            </span>
          )}
        </div>
        <Button size="sm" variant="outline" onClick={onGenerate} disabled={isGenerating}>
          {isGenerating ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
              生成中...
            </>
          ) : checklist ? (
            "重新生成"
          ) : (
            <>
              <Lightbulb className="h-3.5 w-3.5 mr-1" />
              生成研究清单
            </>
          )}
        </Button>
      </div>

      {isGenerating && !checklist && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            正在根据关联画像生成行业针对性研究问题...
          </div>
          <Skeleton className="h-24 w-full" />
        </div>
      )}

      {/* Research Questions */}
      {questions.length > 0 && (
        <div className="space-y-2">
          {questions.map((q) => {
            const linked = evidence.filter((e) => e.linked_question_id === q.id)
            const hasEvidence = linked.length > 0
            return (
              <QuestionCard
                key={q.id}
                question={q}
                linkedEvidence={linked}
                hasEvidence={hasEvidence}
                evidenceForm={evidenceForm}
                onEvidenceFormChange={onEvidenceFormChange}
                onAddEvidence={onAddEvidence}
                onDeleteEvidence={onDeleteEvidence}
                isAddingEvidence={isAddingEvidence}
              />
            )
          })}
        </div>
      )}

      {/* Standalone evidence (not linked to questions) */}
      {evidence.filter((e) => !e.linked_question_id).length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">独立证据</p>
          {evidence
            .filter((e) => !e.linked_question_id)
            .map((e) => (
              <EvidenceItemView key={e.id} item={e} onDelete={onDeleteEvidence} />
            ))}
        </div>
      )}

      {/* Add standalone evidence */}
      {!evidenceForm && (
        <Button
          size="sm"
          variant="ghost"
          className="text-xs"
          onClick={() =>
            onEvidenceFormChange({
              questionId: "",
              content: "",
              impact: "neutral",
              confidence: "medium",
              source: "",
              evidenceType: "observation",
            })
          }
        >
          <Plus className="h-3 w-3 mr-1" />
          添加独立证据
        </Button>
      )}

      {/* Standalone evidence form (not linked to any question) */}
      {evidenceForm && !evidenceForm.questionId && (
        <EvidenceForm
          form={evidenceForm}
          onChange={onEvidenceFormChange}
          onSubmit={onAddEvidence}
          onCancel={() => onEvidenceFormChange(null)}
          isSubmitting={isAddingEvidence}
        />
      )}

      {/* Legacy notes (collapsible) */}
      <Collapsible open={notesOpen} onOpenChange={setNotesOpen}>
        <CollapsibleTrigger className="flex items-center gap-1.5 text-xs w-full hover:text-foreground text-muted-foreground transition-colors">
          {notesOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          研究笔记
          {userNotes.length > 0 && (
            <span className="text-[10px]">({userNotes.length})</span>
          )}
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-2 space-y-2">
          {userNotes.length > 0 && (
            <div className="space-y-1">
              {userNotes.map((note) => (
                <div key={note.id} className="flex items-start gap-2 rounded-md border px-2 py-1.5 text-xs">
                  <Badge className={`text-[8px] px-1 py-0 shrink-0 mt-0.5 ${NOTE_TYPE_COLORS[note.note_type] ?? NOTE_TYPE_COLORS.custom}`}>
                    {NOTE_TYPES.find((t) => t.value === note.note_type)?.label ?? "其他"}
                  </Badge>
                  <span className="flex-1">{note.content}</span>
                  <button
                    onClick={() => onDeleteNote(note.id)}
                    className="text-muted-foreground hover:text-danger transition-colors shrink-0 mt-0.5"
                    disabled={isDeletingNote}
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="space-y-1.5">
            <div className="flex gap-1">
              {NOTE_TYPES.map((t) => (
                <button
                  key={t.value}
                  onClick={() => onNoteTypeChange(t.value)}
                  className={`px-2 py-0.5 text-[10px] rounded-md border transition-colors ${
                    noteType === t.value
                      ? "bg-primary text-primary-foreground border-primary"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div className="flex gap-1.5">
              <Textarea
                placeholder="添加研究笔记 (如: 博纳春节档《蛟龙行动》首日票房3亿)"
                value={noteText}
                onChange={(e) => onNoteTextChange(e.target.value)}
                className="text-xs min-h-[60px] resize-none"
                rows={2}
              />
              <Button
                size="sm"
                variant="outline"
                className="shrink-0 self-end"
                onClick={onAddNote}
                disabled={!noteText.trim() || isAddingNote}
              >
                {isAddingNote ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Plus className="h-3.5 w-3.5" />
                )}
              </Button>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}


// ─── Question Card ──────────────────────────────────────────────────

function QuestionCard({
  question,
  linkedEvidence,
  hasEvidence,
  evidenceForm,
  onEvidenceFormChange,
  onAddEvidence,
  onDeleteEvidence,
  isAddingEvidence,
}: {
  question: ResearchQuestion
  linkedEvidence: EvidenceItem[]
  hasEvidence: boolean
  evidenceForm: ChecklistSectionProps["evidenceForm"]
  onEvidenceFormChange: (v: ChecklistSectionProps["evidenceForm"]) => void
  onAddEvidence: () => void
  onDeleteEvidence: (id: string) => void
  isAddingEvidence: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const showForm = evidenceForm?.questionId === question.id

  return (
    <div className="rounded-md border p-2 space-y-1.5">
      <div className="flex items-start gap-2">
        <button onClick={() => setExpanded(!expanded)} className="shrink-0 mt-0.5">
          {hasEvidence ? (
            <CheckCircle2 className="h-3.5 w-3.5 text-info" />
          ) : (
            <CircleDot className="h-3.5 w-3.5 text-muted-foreground" />
          )}
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <Badge variant="outline" className="text-[8px] px-1 py-0">
              {CATEGORY_LABELS[question.category] ?? question.category}
            </Badge>
            <Badge className={`text-[8px] px-1 py-0 ${PROBABILITY_COLORS[question.priority] ?? ""}`}>
              {question.priority}
            </Badge>
            <span className="text-xs flex-1">{question.text}</span>
          </div>
          {question.data_hint && (
            <p className="text-[10px] text-muted-foreground mt-0.5 flex items-center gap-1">
              <Lightbulb className="h-2.5 w-2.5" />
              {question.data_hint}
            </p>
          )}
        </div>
        <Button
          size="sm"
          variant="ghost"
          className="shrink-0 h-6 w-6 p-0"
          onClick={() => {
            if (showForm) {
              onEvidenceFormChange(null)
            } else {
              onEvidenceFormChange({
                questionId: question.id,
                content: "",
                impact: "neutral",
                confidence: "medium",
                source: "",
                evidenceType: "data_point",
              })
            }
          }}
        >
          <Plus className="h-3 w-3" />
        </Button>
      </div>

      {/* Linked evidence */}
      {linkedEvidence.length > 0 && (
        <div className="ml-5.5 space-y-1">
          {linkedEvidence.map((e) => (
            <EvidenceItemView key={e.id} item={e} onDelete={onDeleteEvidence} compact />
          ))}
        </div>
      )}

      {/* Evidence form */}
      {showForm && evidenceForm && (
        <div className="ml-5.5">
          <EvidenceForm
            form={evidenceForm}
            onChange={onEvidenceFormChange}
            onSubmit={onAddEvidence}
            onCancel={() => onEvidenceFormChange(null)}
            isSubmitting={isAddingEvidence}
          />
        </div>
      )}
    </div>
  )
}


// ─── Evidence Item View ─────────────────────────────────────────────

function EvidenceItemView({
  item,
  onDelete,
  compact,
}: {
  item: EvidenceItem
  onDelete: (id: string) => void
  compact?: boolean
}) {
  const impactCfg = EVIDENCE_IMPACT[item.impact as keyof typeof EVIDENCE_IMPACT] ?? EVIDENCE_IMPACT.neutral
  const ImpactIcon = impactCfg.icon

  return (
    <div className={`flex items-start gap-2 text-xs ${compact ? "py-0.5" : "rounded-md border px-2 py-1.5"}`}>
      <div className="shrink-0 mt-0.5">
        <ImpactIcon className={`h-3 w-3 ${impactCfg.color}`} />
      </div>
      <div className="flex-1 min-w-0">
        <span>{item.content}</span>
        <div className="flex items-center gap-1 mt-0.5">
          <Badge variant="outline" className="text-[8px] px-1 py-0">{impactCfg.label}</Badge>
          <Badge variant="outline" className="text-[8px] px-1 py-0">信心:{item.confidence}</Badge>
          {item.source && (
            <span className="text-[9px] text-muted-foreground flex items-center gap-0.5">
              <Link2 className="h-2 w-2" />{item.source}
            </span>
          )}
        </div>
      </div>
      <button
        onClick={() => onDelete(item.id)}
        className="text-muted-foreground hover:text-danger transition-colors shrink-0 mt-0.5"
      >
        <Trash2 className="h-3 w-3" />
      </button>
    </div>
  )
}


// ─── Evidence Form ──────────────────────────────────────────────────

function EvidenceForm({
  form,
  onChange,
  onSubmit,
  onCancel,
  isSubmitting,
}: {
  form: NonNullable<ChecklistSectionProps["evidenceForm"]>
  onChange: (v: ChecklistSectionProps["evidenceForm"]) => void
  onSubmit: () => void
  onCancel: () => void
  isSubmitting: boolean
}) {
  const update = (patch: Partial<typeof form>) => onChange({ ...form, ...patch })

  return (
    <div className="rounded-md border p-2 space-y-2 bg-muted/30">
      <Textarea
        placeholder="输入证据内容 (如: 猫眼数据显示《蛟龙行动》首日票房3.2亿)"
        value={form.content}
        onChange={(e) => update({ content: e.target.value })}
        className="text-xs min-h-[50px] resize-none"
        rows={2}
      />
      <div className="flex flex-wrap gap-2">
        {/* Impact */}
        <div className="space-y-0.5">
          <p className="text-[9px] text-muted-foreground">影响</p>
          <div className="flex gap-1">
            {(["bullish", "bearish", "neutral"] as const).map((v) => (
              <button
                key={v}
                onClick={() => update({ impact: v })}
                className={`px-1.5 py-0.5 text-[10px] rounded border transition-colors ${
                  form.impact === v ? "bg-primary text-primary-foreground border-primary" : "text-muted-foreground"
                }`}
              >
                {EVIDENCE_IMPACT[v].label}
              </button>
            ))}
          </div>
        </div>
        {/* Confidence */}
        <div className="space-y-0.5">
          <p className="text-[9px] text-muted-foreground">信心</p>
          <div className="flex gap-1">
            {(["low", "medium", "high"] as const).map((v) => (
              <button
                key={v}
                onClick={() => update({ confidence: v })}
                className={`px-1.5 py-0.5 text-[10px] rounded border transition-colors ${
                  form.confidence === v ? "bg-primary text-primary-foreground border-primary" : "text-muted-foreground"
                }`}
              >
                {v === "low" ? "低" : v === "medium" ? "中" : "高"}
              </button>
            ))}
          </div>
        </div>
        {/* Type */}
        <div className="space-y-0.5">
          <p className="text-[9px] text-muted-foreground">类型</p>
          <div className="flex gap-1">
            {(["data_point", "observation", "source_link", "analysis"] as const).map((v) => (
              <button
                key={v}
                onClick={() => update({ evidenceType: v })}
                className={`px-1.5 py-0.5 text-[10px] rounded border transition-colors ${
                  form.evidenceType === v ? "bg-primary text-primary-foreground border-primary" : "text-muted-foreground"
                }`}
              >
                {v === "data_point" ? "数据" : v === "observation" ? "观察" : v === "source_link" ? "链接" : "分析"}
              </button>
            ))}
          </div>
        </div>
      </div>
      <input
        type="text"
        placeholder="数据来源 (如: 猫眼专业版)"
        value={form.source}
        onChange={(e) => update({ source: e.target.value })}
        className="w-full text-xs px-2 py-1 rounded border bg-background"
      />
      <div className="flex justify-end gap-1.5">
        <Button size="sm" variant="ghost" onClick={onCancel} className="text-xs h-7">
          取消
        </Button>
        <Button
          size="sm"
          onClick={onSubmit}
          disabled={!form.content.trim() || isSubmitting}
          className="text-xs h-7"
        >
          {isSubmitting ? <Loader2 className="h-3 w-3 animate-spin" /> : "添加证据"}
        </Button>
      </div>
    </div>
  )
}


// ─── Section 3: Scenario Sandbox ────────────────────────────────────

function ScenarioSandboxSection({
  scenarioResult,
  onAnalyze,
  isAnalyzing,
}: {
  scenarioResult: ScenarioAnalysisResult | null
  onAnalyze: () => void
  isAnalyzing: boolean
}) {
  const scenarios = scenarioResult?.scenarios ?? []

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-medium">
          <GitBranch className="h-3.5 w-3.5" />
          情景分析
        </div>
        <Button size="sm" variant="outline" onClick={onAnalyze} disabled={isAnalyzing}>
          {isAnalyzing ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
              分析中...
            </>
          ) : scenarioResult ? (
            "重新分析"
          ) : (
            "生成情景分析"
          )}
        </Button>
      </div>

      {isAnalyzing && !scenarioResult && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            正在评估乐观/基准/悲观情景...
          </div>
          <Skeleton className="h-24 w-full" />
        </div>
      )}

      {scenarios.length > 0 && (
        <div className="grid gap-2">
          {scenarios.map((s, i) => (
            <ScenarioResultCard key={i} scenario={s} />
          ))}
        </div>
      )}

      {scenarioResult?.status === "error" && (
        <p className="text-xs text-muted-foreground text-center py-2">情景分析暂时不可用，请稍后重试</p>
      )}
    </div>
  )
}

function ScenarioResultCard({ scenario }: { scenario: ScenarioResult }) {
  const [expanded, setExpanded] = useState(false)
  const dir = DIRECTION_LABELS[scenario.price_impact?.direction] ?? DIRECTION_LABELS.flat

  return (
    <div className="rounded-md border p-2 space-y-1.5">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium flex-1">{scenario.name}</span>
        <Badge className={`text-[8px] px-1 py-0 ${PROBABILITY_COLORS[scenario.probability] ?? ""}`}>
          概率:{scenario.probability === "low" ? "低" : scenario.probability === "medium" ? "中" : "高"}
        </Badge>
        <span className={`text-xs font-mono ${dir.color}`}>
          {dir.label}
          {scenario.price_impact?.magnitude && (
            <span className="text-[9px]">({scenario.price_impact.magnitude})</span>
          )}
        </span>
        <button onClick={() => setExpanded(!expanded)} className="text-muted-foreground">
          {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        </button>
      </div>

      {expanded && (
        <div className="space-y-1.5 text-xs pl-1">
          {scenario.key_drivers.length > 0 && (
            <div>
              <p className="text-[9px] text-muted-foreground font-medium">关键驱动</p>
              <ul className="list-disc list-inside text-[11px]">
                {scenario.key_drivers.map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            </div>
          )}
          {scenario.risks.length > 0 && (
            <div>
              <p className="text-[9px] text-muted-foreground font-medium">风险因素</p>
              <ul className="list-disc list-inside text-[11px]">
                {scenario.risks.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          )}
          {scenario.reasoning && (
            <p className="text-[11px] text-muted-foreground">{scenario.reasoning}</p>
          )}
        </div>
      )}
    </div>
  )
}


// ─── Section 4: Comprehensive Analysis ──────────────────────────────

function ComprehensiveAnalysisSection({
  result,
  onAnalyze,
  isAnalyzing,
}: {
  result: ComprehensiveAnalysisResult | null
  onAnalyze: () => void
  isAnalyzing: boolean
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-medium">
          <Brain className="h-3.5 w-3.5" />
          AI 综合研判
          {result && result.evidence_completeness != null && (
            <span className="text-[10px] text-muted-foreground">
              (证据完整度: {Math.round(result.evidence_completeness * 100)}%)
            </span>
          )}
        </div>
        <Button
          size="sm"
          variant={result ? "outline" : "default"}
          onClick={onAnalyze}
          disabled={isAnalyzing}
        >
          {isAnalyzing ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
              分析中...
            </>
          ) : result ? (
            "重新分析"
          ) : (
            "生成综合分析"
          )}
        </Button>
      </div>

      {isAnalyzing && !result && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            正在综合关联画像 + 证据进行深度分析...
          </div>
          <Skeleton className="h-32 w-full" />
        </div>
      )}

      {result && result.status !== "error" && <AnalysisResultView result={result} />}

      {result?.status === "error" && (
        <p className="text-xs text-muted-foreground text-center py-2">分析暂时不可用，请稍后重试</p>
      )}
    </div>
  )
}


// ─── Section 5: Follow-up Q&A ───────────────────────────────────────

function FollowupSection({
  symbol,
  stockName,
  profile,
  qaHistory,
  questionText,
  onQuestionTextChange,
  onAsk,
  isAsking,
}: {
  symbol: string
  stockName: string
  profile: AssociationProfile | null
  qaHistory: FollowupResponse[]
  questionText: string
  onQuestionTextChange: (v: string) => void
  onAsk: () => void
  isAsking: boolean
}) {
  const [dialogOpen, setDialogOpen] = useState(false)

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-medium">
          <MessageSquare className="h-3.5 w-3.5" />
          追问
        </div>
        <Button size="sm" variant="outline" onClick={() => setDialogOpen(true)}>
          <Maximize2 className="h-3.5 w-3.5 mr-1" />
          对话模式
        </Button>
      </div>

      {qaHistory.length > 0 && (
        <div className="space-y-2 max-h-60 overflow-y-auto">
          {qaHistory.map((qa, i) => (
            <div key={i} className="space-y-1 rounded-md border p-2">
              <div className="text-xs font-medium">Q: {qa.question}</div>
              <div className="text-xs text-muted-foreground whitespace-pre-wrap leading-relaxed">{qa.answer}</div>
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-1.5 items-end">
        <Textarea
          placeholder="输入追问 (如: 如果票房超预期会对股价影响多大?)"
          value={questionText}
          onChange={(e) => onQuestionTextChange(e.target.value)}
          className="text-xs min-h-[36px] h-9 resize-none"
          rows={1}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              onAsk()
            }
          }}
        />
        <Button
          size="sm"
          variant="outline"
          className="shrink-0 h-9"
          onClick={onAsk}
          disabled={!questionText.trim() || isAsking}
        >
          {isAsking ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Send className="h-3.5 w-3.5" />
          )}
        </Button>
      </div>

      <ResearchChatDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        symbol={symbol}
        stockName={stockName}
        profile={profile}
      />
    </div>
  )
}


// ─── Research Chat Dialog (multi-turn) ──────────────────────────────

function ResearchChatDialog({
  open,
  onOpenChange,
  symbol,
  stockName,
  profile,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  symbol: string
  stockName: string
  profile: AssociationProfile | null
}) {
  const [input, setInput] = useState("")
  const [contextOpen, setContextOpen] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  const { data: messages = [], isLoading: loadingMessages } = useConversation(symbol, open)
  const followupMutation = useFollowupQuestion(symbol)
  const clearMutation = useClearConversation(symbol)

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, followupMutation.isPending])

  const handleSend = () => {
    const q = input.trim()
    if (!q) return
    setInput("")
    followupMutation.mutate(q, {
      onError: () => toast.error("发送失败，请重试"),
    })
  }

  const handleClear = () => {
    clearMutation.mutate(undefined, {
      onSuccess: () => toast.success("对话已清空"),
      onError: () => toast.error("清空失败"),
    })
  }

  const ip = profile?.industry_profile

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false} className="sm:max-w-5xl h-[85vh] flex flex-col p-0 gap-0">
        {/* Header */}
        <DialogHeader className="px-4 py-3 border-b shrink-0">
          <div className="flex items-center justify-between">
            <DialogTitle className="text-sm flex items-center gap-2">
              <MessageSquare className="h-4 w-4" />
              假期研究对话{stockName ? ` — ${stockName}` : ""}
            </DialogTitle>
            <div className="flex items-center gap-1">
              <Button
                size="sm"
                variant="ghost"
                className="text-xs text-muted-foreground"
                onClick={handleClear}
                disabled={clearMutation.isPending || messages.length === 0}
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" />
                清空对话
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
                onClick={() => onOpenChange(false)}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </DialogHeader>

        {/* Context summary (collapsible) */}
        {profile && (
          <Collapsible open={contextOpen} onOpenChange={setContextOpen} className="border-b shrink-0">
            <CollapsibleTrigger className="flex items-center gap-1.5 text-xs w-full px-4 py-2 hover:bg-muted/50 text-muted-foreground transition-colors">
              {contextOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              <Network className="h-3 w-3" />
              研究上下文
              {ip && <Badge variant="outline" className="text-[8px] px-1 py-0 ml-1">{ip.display}</Badge>}
            </CollapsibleTrigger>
            <CollapsibleContent className="px-4 pb-2 space-y-1">
              {profile.concepts.length > 0 && (
                <p className="text-[10px] text-muted-foreground">
                  概念: {profile.concepts.map((c) => c.name).join(", ")}
                </p>
              )}
              {profile.cross_market_peers.length > 0 && (
                <p className="text-[10px] text-muted-foreground">
                  同行: {profile.cross_market_peers.map((p) => `${p.symbol}(${p.market})`).join(", ")}
                </p>
              )}
              {profile.keyword_themes.length > 0 && (
                <p className="text-[10px] text-muted-foreground">
                  关键词: {profile.keyword_themes.join(", ")}
                </p>
              )}
            </CollapsibleContent>
          </Collapsible>
        )}

        {/* Messages area */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {loadingMessages && messages.length === 0 && (
            <div className="flex items-center justify-center h-full text-muted-foreground text-xs">
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              加载对话历史...
            </div>
          )}

          {!loadingMessages && messages.length === 0 && !followupMutation.isPending && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center space-y-2">
                <MessageSquare className="h-8 w-8 text-muted-foreground/30 mx-auto" />
                <p className="text-xs text-muted-foreground">
                  开始提问，进入多轮对话研究模式
                </p>
                <p className="text-[10px] text-muted-foreground/60">
                  对话历史会自动保存，刷新后可继续
                </p>
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <ChatBubble key={i} message={msg} />
          ))}

          {followupMutation.isPending && (
            <div className="flex gap-2">
              <div className="max-w-[80%] rounded-lg px-3 py-2 text-xs bg-muted">
                <div className="flex items-center gap-1.5 text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  思考中...
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Input area */}
        <div className="border-t px-4 py-3 shrink-0 space-y-1.5">
          <div className="flex gap-2 items-end">
            <Textarea
              placeholder="输入问题 (Enter 发送, Shift+Enter 换行)"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              className="text-sm min-h-[40px] max-h-[100px] resize-none"
              rows={1}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
            />
            <Button
              className="shrink-0 h-10"
              onClick={handleSend}
              disabled={!input.trim() || followupMutation.isPending}
            >
              {followupMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
          </div>
          <p className="text-[10px] text-muted-foreground/50 text-center">
            AI 分析仅供参考，不构成投资建议
          </p>
        </div>
      </DialogContent>
    </Dialog>
  )
}


// ─── Chat Bubble ────────────────────────────────────────────────────

function ChatBubble({ message }: { message: ConversationMessage }) {
  const isUser = message.role === "user"

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-lg px-3 py-2 text-xs leading-relaxed ${
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted"
        }`}
      >
        <div className="whitespace-pre-wrap">{message.content}</div>
        {message.timestamp && (
          <div className={`text-[9px] mt-1 ${isUser ? "text-primary-foreground/60" : "text-muted-foreground/60"}`}>
            {formatTime(message.timestamp)}
          </div>
        )}
      </div>
    </div>
  )
}


// ─── Analysis Result View (reused from v3.2) ────────────────────────

function AnalysisResultView({ result }: { result: ComprehensiveAnalysisResult }) {
  const strat = result.reopening_strategy
  const actionCfg = ACTION_LABELS[strat?.action] ?? ACTION_LABELS.watch
  const confPct = Math.round((strat?.confidence ?? 0) * 100)

  return (
    <div className="space-y-3">
      {/* Association context (new in v3.4) */}
      {result.association_context && (
        <div className="rounded-md border-l-2 border-warning/50 pl-3 py-1">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1">关联上下文</p>
          <p className="text-xs leading-relaxed">{result.association_context}</p>
        </div>
      )}

      {/* Business factors */}
      {result.business_factors.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">业务因子</p>
          {result.business_factors.map((f, i) => {
            const cfg = IMPACT_CONFIG[f.impact as keyof typeof IMPACT_CONFIG] ?? IMPACT_CONFIG.neutral
            const Icon = cfg.icon
            return (
              <div key={i} className="flex items-start gap-2 text-xs">
                <div className={`rounded p-0.5 mt-0.5 ${cfg.bg}`}>
                  <Icon className={`h-3 w-3 ${cfg.color}`} />
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{f.name}</span>
                    <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full bg-primary/60 transition-all"
                        style={{ width: `${Math.round(f.weight * 100)}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-muted-foreground font-mono">{Math.round(f.weight * 100)}%</span>
                  </div>
                  <p className="text-muted-foreground mt-0.5">{f.analysis}</p>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Sector analysis */}
      {result.sector_analysis?.summary && (
        <div className="space-y-1">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">板块分析</p>
          <p className="text-xs">{result.sector_analysis.summary}</p>
          {result.sector_analysis.key_concepts?.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {result.sector_analysis.key_concepts.map((c, i) => (
                <Badge key={i} variant="secondary" className="text-[10px]">{c}</Badge>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Peer comparison */}
      {result.peer_comparison?.summary && (
        <div className="space-y-1">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">同行对比</p>
          <p className="text-xs">{result.peer_comparison.summary}</p>
        </div>
      )}

      {/* Risk matrix */}
      {result.risk_matrix.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider flex items-center gap-1">
            <AlertTriangle className="h-3 w-3" />
            风险矩阵
          </p>
          <div className="space-y-1">
            {result.risk_matrix.map((r, i) => (
              <div key={i} className="flex items-start gap-2 text-xs rounded-md border p-1.5">
                <div className="flex-1">
                  <span className="font-medium">{r.risk}</span>
                  <div className="flex gap-1 mt-0.5">
                    <Badge className={`text-[8px] px-1 py-0 ${PROBABILITY_COLORS[r.probability] ?? ""}`}>
                      概率:{r.probability}
                    </Badge>
                    <Badge className={`text-[8px] px-1 py-0 ${PROBABILITY_COLORS[r.impact] ?? ""}`}>
                      影响:{r.impact}
                    </Badge>
                  </div>
                  {r.mitigation && (
                    <p className="text-muted-foreground mt-0.5">{r.mitigation}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Reopening strategy */}
      {strat && (
        <div className="space-y-1.5 rounded-md border p-2.5">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider flex items-center gap-1">
            <Target className="h-3 w-3" />
            开盘策略
          </p>
          <div className="flex items-center gap-2">
            <Badge className={`text-xs ${actionCfg.color}`}>
              {actionCfg.label}
            </Badge>
            <div className="flex items-center gap-1.5 flex-1">
              <div className="h-1.5 flex-1 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full bg-primary transition-all duration-500"
                  style={{ width: `${confPct}%` }}
                />
              </div>
              <span className="text-xs font-mono text-muted-foreground">{confPct}%</span>
            </div>
          </div>
          {strat.reasoning && (
            <p className="text-xs text-muted-foreground">{strat.reasoning}</p>
          )}
          <div className="flex gap-3 text-xs">
            {strat.target_range?.length === 2 && (
              <span>
                目标价: <span className="font-mono text-market-up">{strat.target_range[0]}</span>
                {" - "}
                <span className="font-mono text-market-up">{strat.target_range[1]}</span>
              </span>
            )}
            {strat.stop_loss != null && (
              <span>
                止损: <span className="font-mono text-market-down">{strat.stop_loss}</span>
              </span>
            )}
          </div>
        </div>
      )}

      {/* Key watch items */}
      {result.key_watch_items.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider flex items-center gap-1">
            <CheckCircle2 className="h-3 w-3" />
            复盘关注清单
          </p>
          <div className="space-y-0.5">
            {result.key_watch_items.map((item, i) => (
              <div key={i} className="flex items-start gap-1.5 text-xs">
                <span className="text-muted-foreground">{i + 1}.</span>
                <span>{item}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Overall assessment */}
      {result.overall_assessment && (
        <div className="rounded-md border-l-2 border-primary/50 pl-3 py-1">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1">综合评估</p>
          <p className="text-xs leading-relaxed">{result.overall_assessment}</p>
        </div>
      )}

      {/* Timestamp */}
      {result.generated_at && (
        <p className="text-[10px] text-muted-foreground text-right">{formatDateTime(result.generated_at)}</p>
      )}
    </div>
  )
}
