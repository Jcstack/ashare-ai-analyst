import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  fetchPrompts,
  fetchPrompt,
  createPrompt,
  updatePrompt,
  deletePrompt,
  testPrompt,
  optimizePrompt,
} from "@/api/prompts"
import type { PromptTemplate } from "@/types/prompt"
import { toast } from "sonner"

const PROMPTS_KEY = ["prompts"]

export function usePrompts() {
  return useQuery({
    queryKey: PROMPTS_KEY,
    queryFn: fetchPrompts,
  })
}

export function usePrompt(id: string | null) {
  return useQuery({
    queryKey: [...PROMPTS_KEY, id],
    queryFn: () => fetchPrompt(id!),
    enabled: !!id,
  })
}

export function useCreatePrompt() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: Partial<PromptTemplate>) => createPrompt(data),
    meta: { skipGlobalError: true },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: PROMPTS_KEY })
      toast.success("Prompt 创建成功")
    },
    onError: () => toast.error("创建失败"),
  })
}

export function useUpdatePrompt() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<PromptTemplate> }) =>
      updatePrompt(id, data),
    meta: { skipGlobalError: true },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: PROMPTS_KEY })
      toast.success("Prompt 已更新")
    },
    onError: () => toast.error("更新失败"),
  })
}

export function useDeletePrompt() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deletePrompt(id),
    meta: { skipGlobalError: true },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: PROMPTS_KEY })
      toast.success("Prompt 已删除")
    },
    onError: () => toast.error("删除失败"),
  })
}

export function useTestPrompt() {
  return useMutation({
    mutationFn: ({
      id,
      variables,
      maxTokens,
      temperature,
    }: {
      id: string
      variables: Record<string, string>
      maxTokens?: number
      temperature?: number
    }) => testPrompt(id, variables, maxTokens, temperature),
  })
}

export function useOptimizePrompt() {
  return useMutation({
    mutationFn: ({ id, testOutput }: { id: string; testOutput?: string }) =>
      optimizePrompt(id, testOutput),
  })
}
