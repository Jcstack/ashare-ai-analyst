/** v12.0 Chat API client — thread-based Agent conversation endpoints. */

import client from "./client"
import type {
  ChatThread,
  ChatMessage,
  CreateThreadResponse,
  ThreadListItem,
  ThreadContext,
} from "@/types/chat"

/** Create a new thread with the first user message. */
export async function createThread(
  message: string,
  context?: ThreadContext,
): Promise<CreateThreadResponse> {
  const { data } = await client.post<CreateThreadResponse>(
    "/chat/threads",
    { message, context },
    { timeout: 360000 }, // 6 min — unified timeout across full chain
  )
  return data
}

/** Send a follow-up message in an existing thread. */
export async function sendMessage(
  threadId: string,
  message: string,
): Promise<ChatMessage> {
  const { data } = await client.post<{ reply: ChatMessage }>(
    `/chat/threads/${threadId}/messages`,
    { message },
    { timeout: 360000 }, // 6 min — unified timeout across full chain
  )
  return data.reply
}

/** List all threads, ordered by most recent. */
export async function listThreads(
  limit = 50,
  offset = 0,
): Promise<{ threads: ThreadListItem[]; total: number }> {
  const { data } = await client.get<{ threads: ThreadListItem[]; total: number }>(
    "/chat/threads",
    { params: { limit, offset } },
  )
  return data
}

/** Get a thread with all its messages. */
export async function getThread(threadId: string): Promise<ChatThread> {
  const { data } = await client.get<ChatThread>(`/chat/threads/${threadId}`)
  return data
}

/** Delete a thread. */
export async function deleteThread(threadId: string): Promise<void> {
  await client.delete(`/chat/threads/${threadId}`)
}

/** Submit feedback on an assistant message. */
export async function submitFeedback(
  threadId: string,
  messageId: string,
  satisfaction: "satisfied" | "unsatisfied",
  feedback?: string,
): Promise<void> {
  await client.post(
    `/chat/threads/${threadId}/messages/${messageId}/feedback`,
    { satisfaction, feedback },
  )
}

/** Quick question suggestion from the backend. */
export interface QuickQuestion {
  icon: string
  label: string
  prompt: string
}

/** Get personalized quick-start suggestions. */
export async function getQuickSuggestions(): Promise<QuickQuestion[]> {
  const { data } = await client.get<{ suggestions: QuickQuestion[] }>(
    "/chat/suggestions",
  )
  return data.suggestions
}
