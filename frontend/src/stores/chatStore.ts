/** v12.0 Chat store — Zustand state for Agent conversation threads. */

import { create } from "zustand"
import { toast } from "sonner"
import type { ChatMessage, ThreadListItem, ThreadContext, IntelCitation } from "@/types/chat"
import * as chatApi from "@/api/chat"
import { getItem as getInfoItem } from "@/api/info-hub"

interface ChatState {
  // Sheet open state
  isOpen: boolean

  // Thread list
  threads: ThreadListItem[]
  threadsLoading: boolean

  // Active thread
  activeThreadId: string | null
  messages: ChatMessage[]
  messagesLoading: boolean

  // Input state
  sending: boolean
  pendingFirstMessage: boolean

  // Pending context for next thread creation
  pendingContext: ThreadContext | null

  // Intel citations for current thread
  intelCitations: IntelCitation[]

  // Error state
  error: string | null

  // Sheet actions
  toggleChat: () => void
  openChat: () => void
  closeChat: () => void

  // Thread actions
  loadThreads: () => Promise<void>
  loadThread: (threadId: string) => Promise<void>
  createThread: (message: string, context?: ThreadContext) => Promise<string | null>
  sendMessage: (message: string) => Promise<void>
  deleteThread: (threadId: string) => Promise<void>
  setActiveThread: (threadId: string | null) => void
  clearActive: () => void
  clearError: () => void
  setIntelCitations: (citations: IntelCitation[]) => void

  // Context-aware open
  openChatWithContext: (context: ThreadContext, initialMessage?: string) => void

  // Feedback & retry actions
  submitFeedback: (messageId: string, satisfaction: "satisfied" | "unsatisfied", feedback?: string) => Promise<void>
  retryMessage: (userMessageId: string) => void
  regenerateWithFeedback: (assistantMessageId: string, feedback: string) => void
}

function extractErrorMessage(err: unknown): string {
  if (err && typeof err === "object" && "response" in err) {
    const resp = (err as { response?: { data?: { detail?: string } } }).response
    if (resp?.data?.detail) return resp.data.detail
  }
  return "服务暂时不可用，请稍后重试。"
}

export const useChatStore = create<ChatState>((set, get) => ({
  isOpen: false,
  threads: [],
  threadsLoading: false,
  activeThreadId: null,
  messages: [],
  messagesLoading: false,
  sending: false,
  pendingFirstMessage: false,
  intelCitations: [],
  pendingContext: null,
  error: null,

  toggleChat: () => set((s) => ({ isOpen: !s.isOpen })),
  openChat: () => set({ isOpen: true }),
  closeChat: () => set({ isOpen: false }),
  clearError: () => set({ error: null }),
  setIntelCitations: (citations) => set({ intelCitations: citations }),

  loadThreads: async () => {
    set({ threadsLoading: true })
    try {
      const { threads } = await chatApi.listThreads()
      set({ threads, threadsLoading: false })
    } catch {
      set({ threadsLoading: false })
    }
  },

  loadThread: async (threadId: string) => {
    set({ messagesLoading: true, activeThreadId: threadId, error: null, intelCitations: [] })
    try {
      const thread = await chatApi.getThread(threadId)
      set({
        messages: thread.messages,
        messagesLoading: false,
        activeThreadId: threadId,
      })

      // Load intel citations from thread context
      const ids = thread.context?.intel_item_ids
      if (ids?.length) {
        const results = await Promise.allSettled(ids.map((id) => getInfoItem(id)))
        const citations: IntelCitation[] = results.flatMap((r) =>
          r.status === "fulfilled"
            ? [{ title: r.value.title, source_name: r.value.source_name, item_id: r.value.item_id, url: r.value.url }]
            : [],
        )
        set({ intelCitations: citations })
      }
    } catch {
      set({ messagesLoading: false })
    }
  },

  createThread: async (message: string, context?: ThreadContext) => {
    // Use explicit context, or fall back to pendingContext
    const effectiveContext = context ?? get().pendingContext ?? undefined
    set({ sending: true, pendingFirstMessage: true, pendingContext: null, error: null })

    // Optimistic: show user message immediately
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: message,
      timestamp: new Date().toISOString(),
    }
    set({ messages: [userMsg] })

    try {
      const resp = await chatApi.createThread(message, effectiveContext)
      const threadId = resp.thread_id

      set({ activeThreadId: threadId })

      if (resp.processing_status === "processing") {
        // Background processing — poll until ready
        await chatApi.pollThreadUntilReady(threadId, (thread) => {
          // Update messages as they appear during polling
          if (thread.messages.length > 0) {
            set({ messages: thread.messages })
          }
        })

        // Final load to get complete thread state
        const finalThread = await chatApi.getThread(threadId)
        set({
          messages: finalThread.messages,
          sending: false,
          pendingFirstMessage: false,
        })
      } else if (resp.reply) {
        // Synchronous response (legacy path)
        set({
          messages: [userMsg, resp.reply],
          sending: false,
          pendingFirstMessage: false,
        })
      }

      // Refresh thread list in background
      get().loadThreads()

      return threadId
    } catch (err) {
      const errorMsg = extractErrorMessage(err)
      // Show error as an assistant message so user sees it inline
      const errorReply: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: errorMsg,
        timestamp: new Date().toISOString(),
        _isError: true,
      }
      set({
        messages: [userMsg, errorReply],
        sending: false,
        pendingFirstMessage: false,
        error: errorMsg,
      })
      return null
    }
  },

  sendMessage: async (message: string) => {
    const { activeThreadId } = get()
    if (!activeThreadId) return

    // Optimistic: add user message immediately
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: message,
      timestamp: new Date().toISOString(),
    }

    set((state) => ({ messages: [...state.messages, userMsg], sending: true, error: null }))

    try {
      const reply = await chatApi.sendMessage(activeThreadId, message)
      set((state) => ({
        messages: [...state.messages, reply],
        sending: false,
      }))

      // Refresh thread list to update timestamps
      get().loadThreads()
    } catch (err) {
      const errorMsg = extractErrorMessage(err)
      const errorReply: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: errorMsg,
        timestamp: new Date().toISOString(),
        _isError: true,
      }
      set((state) => ({
        messages: [...state.messages, errorReply],
        sending: false,
        error: errorMsg,
      }))
    }
  },

  deleteThread: async (threadId: string) => {
    try {
      await chatApi.deleteThread(threadId)
      const { activeThreadId } = get()
      set((state) => ({
        threads: state.threads.filter((t) => t.id !== threadId),
        ...(activeThreadId === threadId
          ? { activeThreadId: null, messages: [] }
          : {}),
      }))
    } catch {
      toast.error("删除对话失败")
    }
  },

  setActiveThread: (threadId: string | null) => {
    if (threadId) {
      get().loadThread(threadId)
    } else {
      set({ activeThreadId: null, messages: [], error: null })
    }
  },

  clearActive: () => {
    set({ activeThreadId: null, messages: [], error: null, intelCitations: [] })
  },

  openChatWithContext: (context: ThreadContext, initialMessage?: string) => {
    // Clear active thread so we start fresh
    set({ isOpen: true, activeThreadId: null, messages: [], pendingContext: context, intelCitations: [] })
    if (initialMessage) {
      // Immediately create thread with context + message
      get().createThread(initialMessage, context)
    }
  },

  submitFeedback: async (messageId, satisfaction, feedback?) => {
    const { activeThreadId, messages } = get()
    if (!activeThreadId) return

    // Optimistic update
    set({
      messages: messages.map((m) =>
        m.id === messageId ? { ...m, satisfaction, feedback: feedback ?? m.feedback } : m,
      ),
    })

    try {
      await chatApi.submitFeedback(activeThreadId, messageId, satisfaction, feedback)
    } catch {
      toast.error("提交反馈失败")
    }
  },

  retryMessage: (userMessageId) => {
    const { messages } = get()
    const idx = messages.findIndex((m) => m.id === userMessageId)
    if (idx === -1) return

    const userMsg = messages[idx]
    const nextMsg = messages[idx + 1]

    // Remove the error reply that follows the user message
    if (nextMsg?.role === "assistant" && nextMsg._isError) {
      set({ messages: messages.filter((_, i) => i !== idx + 1) })
    }

    // Re-send the original message
    get().sendMessage(userMsg.content)
  },

  regenerateWithFeedback: (assistantMessageId, feedback) => {
    const { messages } = get()
    const assistantIdx = messages.findIndex((m) => m.id === assistantMessageId)
    if (assistantIdx === -1) return

    // Find the user message that precedes this assistant reply
    let userContent = ""
    for (let i = assistantIdx - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        userContent = messages[i].content
        break
      }
    }
    if (!userContent) return

    const newContent =
      `[用户补充反馈] 我对上一次回答不满意。反馈: ${feedback}\n请根据反馈重新回答: ${userContent}`
    get().sendMessage(newContent)
  },
}))
