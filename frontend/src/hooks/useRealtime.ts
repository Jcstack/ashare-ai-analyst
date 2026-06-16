import { useCallback, useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import type { RealtimeQuote } from "@/types/market"

// Re-export the WebSocket-first hook for callers that want WS→SSE→polling
export { useRealtimeWS } from "./useRealtimeWS"

/**
 * SSE-based real-time quote hook with automatic fallback to polling.
 *
 * Connects to /api/v1/market/stream for live updates. Falls back
 * to the existing useRealtimeQuotes polling if SSE fails.
 *
 * For WebSocket-first transport (QMT push), use useRealtimeWS instead.
 */
export function useRealtimeSSE(symbols: string[]) {
  const [quotes, setQuotes] = useState<Map<string, RealtimeQuote>>(new Map())
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const eventSourceRef = useRef<EventSource | null>(null)
  const queryClient = useQueryClient()

  const connect = useCallback(() => {
    if (!symbols.length) return

    const symbolParam = symbols.join(",")
    const url = `/api/v1/market/stream?symbols=${symbolParam}`

    try {
      const es = new EventSource(url)
      eventSourceRef.current = es

      es.onopen = () => {
        setConnected(true)
        setError(null)
      }

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as RealtimeQuote[]
          setQuotes((prev) => {
            const next = new Map(prev)
            for (const q of data) {
              next.set(q.symbol, q)
            }
            return next
          })
          // Merge into react-query cache (preserve quotes for symbols not in this batch)
          queryClient.setQueryData(
            ["realtime-quotes", undefined],
            (old: RealtimeQuote[] | undefined) => {
              if (!old) return data
              const map = new Map(old.map((q) => [q.symbol, q]))
              for (const q of data) map.set(q.symbol, q)
              return Array.from(map.values())
            },
          )
        } catch {
          // Ignore parse errors for non-JSON events (keepalive, etc.)
        }
      }

      es.onerror = () => {
        setConnected(false)
        setError("SSE connection lost, falling back to polling")
        es.close()
        eventSourceRef.current = null
        // Retry after 30 seconds
        setTimeout(() => connect(), 30_000)
      }
    } catch {
      setError("SSE not supported, using polling")
    }
  }, [symbols, queryClient])

  useEffect(() => {
    connect()
    return () => {
      eventSourceRef.current?.close()
      eventSourceRef.current = null
    }
  }, [connect])

  return {
    quotes,
    connected,
    error,
    quotesArray: Array.from(quotes.values()),
  }
}
