import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  fetchResearchContext,
  addUserNote,
  deleteUserNote,
  fetchEvidence,
  addEvidence,
  deleteEvidence,
  generateResearchQuestions,
  analyzeScenarios,
  analyzeComprehensive,
  askFollowup,
  fetchConversation,
  clearConversation,
  fetchProfileOverrides,
  updateProfileOverrides,
  deleteProfileOverrides,
  fetchAvailableIndustries,
} from "@/api/holiday-research"
import type { Scenario, ProfileOverrideRequest } from "@/types/holiday-research"

export function useResearchContext(symbol: string, enabled = false) {
  return useQuery({
    queryKey: ["holiday-research-context", symbol],
    queryFn: () => fetchResearchContext(symbol),
    enabled: !!symbol && enabled,
    staleTime: 5 * 60 * 1000, // 5 min
    gcTime: 30 * 60 * 1000,
    retry: 1,
  })
}

export function useAddNote(symbol: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ content, noteType }: { content: string; noteType: string }) =>
      addUserNote(symbol, content, noteType),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["holiday-research-context", symbol] })
    },
  })
}

export function useDeleteNote(symbol: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (noteId: string) => deleteUserNote(symbol, noteId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["holiday-research-context", symbol] })
    },
  })
}

// --- v3.4: Evidence ---

export function useEvidence(symbol: string, enabled = false) {
  return useQuery({
    queryKey: ["holiday-research-evidence", symbol],
    queryFn: () => fetchEvidence(symbol),
    enabled: !!symbol && enabled,
    staleTime: 2 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    retry: 1,
  })
}

export function useAddEvidence(symbol: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      content: string
      evidence_type: string
      linked_question_id: string
      impact: string
      confidence: string
      source: string
    }) => addEvidence(symbol, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["holiday-research-evidence", symbol] })
    },
  })
}

export function useDeleteEvidence(symbol: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (evidenceId: string) => deleteEvidence(symbol, evidenceId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["holiday-research-evidence", symbol] })
    },
  })
}

// --- v3.4: Research Questions ---

export function useGenerateQuestions(symbol: string) {
  return useMutation({
    mutationFn: () => generateResearchQuestions(symbol),
  })
}

// --- v3.4: Scenario Analysis ---

export function useScenarioAnalysis(symbol: string) {
  return useMutation({
    mutationFn: (scenarios?: Scenario[]) => analyzeScenarios(symbol, scenarios),
  })
}

// --- Comprehensive Analysis + Follow-up ---

export function useComprehensiveAnalysis(symbol: string) {
  return useMutation({
    mutationFn: () => analyzeComprehensive(symbol),
  })
}

export function useFollowupQuestion(symbol: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (question: string) => askFollowup(symbol, question),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["holiday-research-conversation", symbol] })
    },
  })
}

// --- Conversation ---

export function useConversation(symbol: string, enabled = false) {
  return useQuery({
    queryKey: ["holiday-research-conversation", symbol],
    queryFn: () => fetchConversation(symbol),
    enabled: !!symbol && enabled,
    staleTime: 30 * 1000, // 30s
    gcTime: 5 * 60 * 1000,
    retry: 1,
  })
}

export function useClearConversation(symbol: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => clearConversation(symbol),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["holiday-research-conversation", symbol] })
    },
  })
}

// --- Profile Overrides ---

export function useProfileOverrides(symbol: string, enabled = false) {
  return useQuery({
    queryKey: ["profile-overrides", symbol],
    queryFn: () => fetchProfileOverrides(symbol),
    enabled: !!symbol && enabled,
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    retry: 1,
  })
}

export function useUpdateProfileOverrides(symbol: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ProfileOverrideRequest) => updateProfileOverrides(symbol, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile-overrides", symbol] })
      qc.invalidateQueries({ queryKey: ["holiday-research-context", symbol] })
    },
  })
}

export function useDeleteProfileOverrides(symbol: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => deleteProfileOverrides(symbol),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile-overrides", symbol] })
      qc.invalidateQueries({ queryKey: ["holiday-research-context", symbol] })
    },
  })
}

export function useAvailableIndustries(enabled = false) {
  return useQuery({
    queryKey: ["available-industries"],
    queryFn: fetchAvailableIndustries,
    enabled,
    staleTime: 60 * 60 * 1000, // 1 hour
    gcTime: 120 * 60 * 1000,
  })
}
