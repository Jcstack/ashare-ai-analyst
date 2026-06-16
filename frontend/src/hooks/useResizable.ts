/** Reusable drag-to-resize hook for sidebar panels. */

import { useCallback, useEffect, useRef, useState } from "react"

interface UseResizableOptions {
  /** localStorage key for persistence */
  storageKey?: string
  /** Default width in px */
  defaultWidth?: number
  /** Minimum width in px */
  minWidth?: number
  /** Maximum width in px */
  maxWidth?: number
  /** Which side the panel is on — affects drag direction */
  side?: "left" | "right"
}

interface UseResizableReturn {
  width: number
  handleMouseDown: (e: React.MouseEvent) => void
  isResizing: boolean
}

export function useResizable({
  storageKey = "sidebar-width",
  defaultWidth = 240,
  minWidth = 180,
  maxWidth = 420,
  side = "left",
}: UseResizableOptions = {}): UseResizableReturn {
  const [width, setWidth] = useState(() => {
    if (typeof window === "undefined") return defaultWidth
    const stored = localStorage.getItem(storageKey)
    if (stored) {
      const parsed = parseInt(stored, 10)
      if (!isNaN(parsed) && parsed >= minWidth && parsed <= maxWidth) return parsed
    }
    return defaultWidth
  })

  const isResizing = useRef(false)
  const [resizing, setResizing] = useState(false)

  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      if (!isResizing.current) return
      const raw = side === "right" ? window.innerWidth - e.clientX : e.clientX
      const newWidth = Math.min(maxWidth, Math.max(minWidth, raw))
      setWidth(newWidth)
    },
    [minWidth, maxWidth, side],
  )

  const handleMouseUp = useCallback(() => {
    if (!isResizing.current) return
    isResizing.current = false
    setResizing(false)
    document.body.style.cursor = ""
    document.body.style.userSelect = ""
  }, [])

  // Track previous resizing state to detect resize-end transition
  const wasResizing = useRef(false)

  // Persist width to localStorage only when resizing ends (transition true→false)
  useEffect(() => {
    if (wasResizing.current && !resizing) {
      localStorage.setItem(storageKey, String(width))
    }
    wasResizing.current = resizing
  }, [resizing, width, storageKey])

  // Attach/detach global listeners
  useEffect(() => {
    if (resizing) {
      document.addEventListener("mousemove", handleMouseMove)
      document.addEventListener("mouseup", handleMouseUp)
    }
    return () => {
      document.removeEventListener("mousemove", handleMouseMove)
      document.removeEventListener("mouseup", handleMouseUp)
    }
  }, [resizing, handleMouseMove, handleMouseUp])

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    isResizing.current = true
    setResizing(true)
    document.body.style.cursor = "col-resize"
    document.body.style.userSelect = "none"
  }, [])

  return { width, handleMouseDown, isResizing: resizing }
}
