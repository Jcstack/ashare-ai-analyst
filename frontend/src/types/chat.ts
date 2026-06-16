/** v12.0 Chat types — thread-based Agent conversation with rich cards. */

export interface RichCard {
  type: string
  props: Record<string, unknown>
}

export interface ToolCallRecord {
  tool_name: string
  input: Record<string, unknown>
  output_summary: string
  duration_ms: number
}

export interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  rich_cards?: RichCard[] | null
  tool_calls?: ToolCallRecord[] | null
  timestamp: string
  agent_name?: string | null
  delegation_chain?: string[] | null
  satisfaction?: "satisfied" | "unsatisfied" | null
  feedback?: string | null
  /** Client-only flag: marks error placeholder messages (not persisted). */
  _isError?: boolean
}

export interface ThreadContext {
  symbol?: string | null
  mode: "stock" | "portfolio" | "market" | "general"
  intel_item_ids?: string[]
  /** Portfolio/watchlist symbols that overlap with the selected intel items' related_symbols. */
  matched_portfolio_symbols?: string[]
}

export interface ChatThread {
  id: string
  title: string
  messages: ChatMessage[]
  context?: ThreadContext | null
  created_at: string
  updated_at: string
}

export interface ThreadListItem {
  id: string
  title: string
  context?: ThreadContext | null
  created_at: string
  updated_at: string
}

export interface IntelCitation {
  title: string
  source_name: string
  item_id: string
  url?: string
}

// API request/response shapes
export interface CreateThreadRequest {
  message: string
  context?: ThreadContext
  use_multi_agent?: boolean
}

export interface CreateThreadResponse {
  thread_id: string
  reply: ChatMessage
}

export interface SendMessageRequest {
  message: string
  use_multi_agent?: boolean
}

export interface SendMessageResponse {
  reply: ChatMessage
}

export interface ThreadListResponse {
  threads: ThreadListItem[]
  total: number
}
