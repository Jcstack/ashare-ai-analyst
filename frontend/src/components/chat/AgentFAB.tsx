/** Floating action button — opens the Agent chat sheet. */

import { BrainCircuit } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useChatStore } from "@/stores/chatStore"

export function AgentFAB() {
  const { isOpen, toggleChat } = useChatStore()

  if (isOpen) return null

  return (
    <Button
      size="icon"
      className="fixed bottom-6 right-6 z-50 h-12 w-12 rounded-full shadow-lg"
      onClick={toggleChat}
      aria-label="打开投研 Agent"
    >
      <BrainCircuit className="h-5 w-5" />
    </Button>
  )
}
