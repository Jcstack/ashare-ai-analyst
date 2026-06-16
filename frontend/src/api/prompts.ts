import client from "./client"
import type {
  PromptTemplate,
  PromptListItem,
  PromptTestResult,
  PromptOptimizeResult,
} from "@/types/prompt"

export async function fetchPrompts(): Promise<PromptListItem[]> {
  const { data } = await client.get("/prompts")
  return data
}

export async function fetchPrompt(id: string): Promise<PromptTemplate> {
  const { data } = await client.get(`/prompts/${id}`)
  return data
}

export async function createPrompt(
  prompt: Partial<PromptTemplate>,
): Promise<PromptTemplate> {
  const { data } = await client.post("/prompts", prompt)
  return data
}

export async function updatePrompt(
  id: string,
  updates: Partial<PromptTemplate>,
): Promise<PromptTemplate> {
  const { data } = await client.put(`/prompts/${id}`, updates)
  return data
}

export async function deletePrompt(id: string): Promise<void> {
  await client.delete(`/prompts/${id}`)
}

export async function testPrompt(
  id: string,
  variables: Record<string, string>,
  maxTokens?: number,
  temperature?: number,
): Promise<PromptTestResult> {
  const { data } = await client.post(`/prompts/${id}/test`, {
    variables,
    max_tokens: maxTokens,
    temperature,
  })
  return data
}

export async function optimizePrompt(
  id: string,
  testOutput?: string,
): Promise<PromptOptimizeResult> {
  const { data } = await client.post(`/prompts/${id}/optimize`, {
    test_output: testOutput,
  })
  return data
}
