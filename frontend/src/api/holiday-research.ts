import client from "./client"
import type {
  HolidayResearchContext,
  UserNote,
  EvidenceItem,
  ResearchChecklist,
  Scenario,
  ScenarioAnalysisResult,
  ComprehensiveAnalysisResult,
  FollowupResponse,
  ConversationMessage,
  ProfileOverride,
  ProfileOverrideRequest,
  IndustryOption,
} from "@/types/holiday-research"

const BASE = "/advisor/holiday-research"

export async function fetchResearchContext(symbol: string): Promise<HolidayResearchContext> {
  const { data } = await client.get<HolidayResearchContext>(`${BASE}/${symbol}/context`)
  return data
}

export async function fetchUserNotes(symbol: string, holidayKey?: string): Promise<UserNote[]> {
  const params = holidayKey ? `?holiday_key=${holidayKey}` : ""
  const { data } = await client.get<UserNote[]>(`${BASE}/${symbol}/notes${params}`)
  return data
}

export async function addUserNote(
  symbol: string,
  content: string,
  noteType: string,
  holidayKey?: string,
): Promise<UserNote> {
  const params = holidayKey ? `?holiday_key=${holidayKey}` : ""
  const { data } = await client.post<UserNote>(`${BASE}/${symbol}/notes${params}`, {
    content,
    note_type: noteType,
  })
  return data
}

export async function deleteUserNote(
  symbol: string,
  noteId: string,
  holidayKey?: string,
): Promise<{ status: string }> {
  const params = holidayKey ? `?holiday_key=${holidayKey}` : ""
  const { data } = await client.delete<{ status: string }>(`${BASE}/${symbol}/notes/${noteId}${params}`)
  return data
}

// --- v3.4: Evidence CRUD ---

export async function fetchEvidence(symbol: string, holidayKey?: string): Promise<EvidenceItem[]> {
  const params = holidayKey ? `?holiday_key=${holidayKey}` : ""
  const { data } = await client.get<EvidenceItem[]>(`${BASE}/${symbol}/evidence${params}`)
  return data
}

export async function addEvidence(
  symbol: string,
  body: {
    content: string
    evidence_type: string
    linked_question_id: string
    impact: string
    confidence: string
    source: string
  },
  holidayKey?: string,
): Promise<EvidenceItem> {
  const params = holidayKey ? `?holiday_key=${holidayKey}` : ""
  const { data } = await client.post<EvidenceItem>(`${BASE}/${symbol}/evidence${params}`, body)
  return data
}

export async function deleteEvidence(
  symbol: string,
  evidenceId: string,
  holidayKey?: string,
): Promise<{ status: string }> {
  const params = holidayKey ? `?holiday_key=${holidayKey}` : ""
  const { data } = await client.delete<{ status: string }>(`${BASE}/${symbol}/evidence/${evidenceId}${params}`)
  return data
}

// --- v3.4: Research Questions ---

export async function generateResearchQuestions(symbol: string): Promise<ResearchChecklist> {
  const { data } = await client.post<ResearchChecklist>(`${BASE}/${symbol}/research-questions`)
  return data
}

// --- v3.4: Scenario Analysis ---

export async function analyzeScenarios(
  symbol: string,
  scenarios?: Scenario[],
  holidayKey?: string,
): Promise<ScenarioAnalysisResult> {
  const params = holidayKey ? `?holiday_key=${holidayKey}` : ""
  const body = scenarios ? { scenarios } : undefined
  const { data } = await client.post<ScenarioAnalysisResult>(`${BASE}/${symbol}/scenarios${params}`, body)
  return data
}

// --- Comprehensive Analysis + Follow-up ---

export async function analyzeComprehensive(
  symbol: string,
  holidayKey?: string,
): Promise<ComprehensiveAnalysisResult> {
  const params = holidayKey ? `?holiday_key=${holidayKey}` : ""
  const { data } = await client.post<ComprehensiveAnalysisResult>(`${BASE}/${symbol}/analyze${params}`)
  return data
}

export async function askFollowup(
  symbol: string,
  question: string,
  holidayKey?: string,
): Promise<FollowupResponse> {
  const params = holidayKey ? `?holiday_key=${holidayKey}` : ""
  const { data } = await client.post<FollowupResponse>(`${BASE}/${symbol}/ask${params}`, {
    question,
  })
  return data
}

// --- Conversation ---

export async function fetchConversation(
  symbol: string,
  holidayKey?: string,
): Promise<ConversationMessage[]> {
  const params = holidayKey ? `?holiday_key=${holidayKey}` : ""
  const { data } = await client.get<ConversationMessage[]>(`${BASE}/${symbol}/conversation${params}`)
  return data
}

export async function clearConversation(
  symbol: string,
  holidayKey?: string,
): Promise<{ status: string }> {
  const params = holidayKey ? `?holiday_key=${holidayKey}` : ""
  const { data } = await client.delete<{ status: string }>(`${BASE}/${symbol}/conversation${params}`)
  return data
}

// --- Profile Overrides ---

export async function fetchProfileOverrides(symbol: string): Promise<ProfileOverride> {
  const { data } = await client.get<ProfileOverride>(`${BASE}/${symbol}/profile-overrides`)
  return data
}

export async function updateProfileOverrides(
  symbol: string,
  body: ProfileOverrideRequest,
): Promise<ProfileOverride> {
  const { data } = await client.put<ProfileOverride>(`${BASE}/${symbol}/profile-overrides`, body)
  return data
}

export async function deleteProfileOverrides(symbol: string): Promise<{ status: string }> {
  const { data } = await client.delete<{ status: string }>(`${BASE}/${symbol}/profile-overrides`)
  return data
}

export async function fetchAvailableIndustries(): Promise<IndustryOption[]> {
  const { data } = await client.get<{ industries: IndustryOption[] }>(`${BASE}/industries`)
  return data.industries
}
