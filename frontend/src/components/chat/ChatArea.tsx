/** Chat area — message list + input bar, or welcome screen if no thread. */

import { useChatStore } from "@/stores/chatStore"
import { MessageList } from "./MessageList"
import { ChatInputBar } from "./ChatInputBar"
import { WelcomeScreen } from "./WelcomeScreen"

export function ChatArea() {
  const {
    activeThreadId,
    messages,
    messagesLoading,
    sending,
    createThread,
    sendMessage,
  } = useChatStore()

  const handleSend = (message: string) => {
    if (activeThreadId) {
      sendMessage(message)
    } else {
      createThread(message)
    }
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {activeThreadId ? (
        <>
          <MessageList messages={messages} loading={messagesLoading || sending} />
          <ChatInputBar
            onSend={handleSend}
            sending={sending}
            disabled={messagesLoading}
          />
        </>
      ) : (
        <>
          <WelcomeScreen onSend={handleSend} />
          <ChatInputBar
            onSend={handleSend}
            sending={sending}
            placeholder="问我任何关于 A 股投资的问题..."
          />
        </>
      )}
    </div>
  )
}
