import { Outlet } from "react-router-dom"
import { Sidebar } from "./Sidebar"
import { MobileHeader } from "./MobileHeader"
import { Toaster } from "@/components/ui/sonner"
import { ErrorBoundary } from "@/components/ErrorBoundary"
import { useResizable } from "@/hooks/useResizable"
import { ChatSheet } from "@/components/chat/ChatSheet"
import { AgentFAB } from "@/components/chat/AgentFAB"

export function Layout() {
  const { width, handleMouseDown, isResizing } = useResizable()

  return (
    <div className="flex h-screen overflow-hidden">
      <div className="hidden lg:flex" style={{ width }}>
        <Sidebar />
      </div>
      {/* Drag handle */}
      <div
        onMouseDown={handleMouseDown}
        className={`hidden lg:block w-1 cursor-col-resize hover:bg-border transition-colors shrink-0 ${isResizing ? "bg-border" : ""}`}
      />
      <div className="flex flex-1 flex-col overflow-hidden">
        <MobileHeader />
        <main className="flex-1 overflow-y-auto px-8 py-7">
          <ErrorBoundary>
            <div className="page-enter mx-auto max-w-6xl">
              <Outlet />
            </div>
          </ErrorBoundary>
        </main>
      </div>
      <ChatSheet />
      <AgentFAB />
      <Toaster />
    </div>
  )
}
