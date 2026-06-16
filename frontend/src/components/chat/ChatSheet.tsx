/** Chat sheet — right-side panel containing the Agent chat interface. */

import { useEffect } from "react"
import { ArrowLeft, Clock, Plus, X } from "lucide-react"
import {
  Sheet,
  SheetContent,
  SheetTitle,
} from "@/components/ui/sheet"
import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { useChatStore } from "@/stores/chatStore"
import { useResizable } from "@/hooks/useResizable"
import { ThreadSidebar } from "./ThreadSidebar"
import { MessageList } from "./MessageList"
import { ChatInputBar } from "./ChatInputBar"
import { WelcomeScreen } from "./WelcomeScreen"

export function ChatSheet() {
  const {
    isOpen,
    closeChat,
    activeThreadId,
    messages,
    messagesLoading,
    sending,
    pendingFirstMessage,
    createThread,
    sendMessage,
    clearActive,
    threads,
    submitFeedback,
    retryMessage,
    regenerateWithFeedback,
  } = useChatStore()

  const intelCitations = useChatStore((s) => s.intelCitations)
  const loadThreads = useChatStore((s) => s.loadThreads)

  const { width, handleMouseDown, isResizing } = useResizable({
    storageKey: "chat-width",
    defaultWidth: 420,
    minWidth: 340,
    maxWidth: 720,
    side: "right",
  })

  // Load thread list when sheet opens
  useEffect(() => {
    if (isOpen) {
      loadThreads()
    }
  }, [isOpen, loadThreads])

  const handleSend = (message: string) => {
    if (activeThreadId) {
      sendMessage(message)
    } else {
      createThread(message)
    }
  }

  // Find active thread title
  const activeTitle = threads.find((t) => t.id === activeThreadId)?.title

  return (
    <Sheet open={isOpen} onOpenChange={(open) => !open && closeChat()}>
      <SheetContent
        side="right"
        showCloseButton={false}
        className="w-full p-0 gap-0 flex flex-col"
        style={{ width, maxWidth: width }}
      >
        {/* Drag handle — left edge */}
        <div
          className={`absolute left-0 top-0 bottom-0 w-1 cursor-col-resize z-10 hidden sm:block hover:bg-accent-primary/30 transition-colors ${isResizing ? "bg-accent-primary/30" : ""}`}
          onMouseDown={handleMouseDown}
        />
        {/* Header */}
        <div className="flex items-center gap-2 border-b px-4 py-3 shrink-0">
          {activeThreadId ? (
            <>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                onClick={() => clearActive()}
              >
                <ArrowLeft className="h-4 w-4" />
              </Button>
              <SheetTitle className="flex-1 truncate text-sm">
                {activeTitle || "对话"}
              </SheetTitle>
            </>
          ) : (
            <>
              <SheetTitle className="flex-1 text-sm">投研 Agent</SheetTitle>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                onClick={() => clearActive()}
                title="新对话"
              >
                <Plus className="h-4 w-4" />
              </Button>
            </>
          )}
          {/* History popover */}
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                title="对话历史"
              >
                <Clock className="h-4 w-4" />
              </Button>
            </PopoverTrigger>
            <PopoverContent
              side="bottom"
              align="end"
              className="w-72 p-0 max-h-80 overflow-y-auto"
            >
              <ThreadSidebar embedded maxAgeDays={3} />
            </PopoverContent>
          </Popover>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0"
            onClick={closeChat}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Body */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {activeThreadId || pendingFirstMessage ? (
            <>
              <MessageList
                messages={messages}
                loading={messagesLoading || sending}
                threadId={activeThreadId}
                citations={intelCitations}
                onRetry={(id) => retryMessage(id)}
                onSubmitFeedback={(id, sat, fb) => submitFeedback(id, sat, fb)}
                onRegenerateWithFeedback={(id, fb) => regenerateWithFeedback(id, fb)}
              />
              <ChatInputBar
                onSend={handleSend}
                sending={sending}
                disabled={messagesLoading}
              />
            </>
          ) : (
            <>
              <div className="flex-1 overflow-y-auto">
                <WelcomeScreen onSend={handleSend} />
              </div>
              <ChatInputBar
                onSend={handleSend}
                sending={sending}
                placeholder="问我任何关于 A 股投资的问题..."
              />
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
