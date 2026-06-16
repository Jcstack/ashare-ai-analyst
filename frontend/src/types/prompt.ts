export interface PromptTemplate {
  id: string
  name: string
  category: string
  description: string
  system_template: string
  user_template: string
  variables: string[]
  tags: string[]
  usage_count: number
  created_at: string | null
  updated_at: string | null
  version_history?: PromptVersion[]
}

export interface PromptVersion {
  version: number
  timestamp: string
  system_template: string
  user_template: string
}

export interface PromptListItem {
  id: string
  name: string
  category: string
  description: string
  tags: string[]
  variables: string[]
  usage_count: number
  updated_at: string | null
  created_at: string | null
}

export interface PromptTestResult {
  status: "success" | "error"
  response?: string
  model?: string
  input_tokens?: number
  output_tokens?: number
  latency_ms?: number
  cost_usd?: number
  rendered_system?: string
  rendered_user?: string
  message?: string
}

export interface PromptOptimizeResult {
  status: "success" | "error"
  overall_score?: number
  suggestions?: Array<{
    aspect: string
    issue: string
    recommendation: string
    priority: "high" | "medium" | "low"
  }>
  improved_system_template?: string
  improved_user_template?: string
  model?: string
  message?: string
}

export const PROMPT_CATEGORIES: Record<string, string> = {
  analysis: "股票分析",
  market: "市场分析",
  prediction: "预测",
  custom: "自定义",
}
