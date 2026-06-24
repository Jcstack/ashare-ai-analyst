/** v12.0 Chat API client — thread-based Agent conversation endpoints.
 *
 * POST /threads returns immediately with processing_status='processing'.
 * Frontend polls GET /threads/:id until status changes to 'ready'.
 */

import client from "./client"
import type {
  ChatThread,
  ChatMessage,
  CreateThreadResponse,
  ThreadListItem,
  ThreadContext,
} from "@/types/chat"

const POLL_INTERVAL_MS = 2000
const POLL_MAX_MS = 600000 // 10 min max poll

/** Create a new thread (returns immediately, processes in background). */
export async function createThread(
  message: string,
  context?: ThreadContext,
): Promise<CreateThreadResponse> {
  const { data } = await client.post<CreateThreadResponse>(
    "/chat/threads",
    { message, context },
    { timeout: 30000 }, // 30s — POST is now fast (just creates thread)
  )
  return data
}

/** Poll a thread until processing completes, returns the final thread. */
export async function pollThreadUntilReady(
  threadId: string,
  onUpdate?: (thread: ChatThread) => void,
): Promise<ChatThread> {
  const start = Date.now()
  while (Date.now() - start < POLL_MAX_MS) {
    const thread = await getThread(threadId)
    onUpdate?.(thread)
    if (thread.processing_status !== "processing") {
      return thread
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
  }
  // Timeout — return whatever we have
  return getThread(threadId)
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
