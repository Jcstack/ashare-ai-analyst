import { useCallback, useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import type { RealtimeQuote } from "@/types/market"

/**
 * WebSocket-based real-time quote hook with automatic SSE fallback.
 *
 * Preferred transport when QMT is active (sub-second latency).
 * Falls back to SSE (/api/v1/market/stream) if WS fails.
 */
export function useRealtimeWS(symbols: string[]) {
  const [quotes, setQuotes] = useState<Map<string, RealtimeQuote>>(new Map())
  const [connected, setConnected] = useState(false)
  const [transport, setTransport] = useState<"ws" | "sse" | "none">("none")
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const sseRef = useRef<EventSource | null>(null)
  const queryClient = useQueryClient()
  const retryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleQuotes = useCallback(
    (data: RealtimeQuote[]) => {
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
    },
    [queryClient],
  )

  const connectSSE = useCallback(() => {
    if (!symbols.length) return

    const symbolParam = symbols.join(",")
    const url = `/api/v1/market/stream?symbols=${symbolParam}`

    try {
      const es = new EventSource(url)
      sseRef.current = es

      es.onopen = () => {
        setConnected(true)
        setTransport("sse")
        setError(null)
      }

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as RealtimeQuote[]
          handleQuotes(data)
        } catch {
          // Ignore parse errors for keepalive events
        }
      }

      es.onerror = () => {
        setConnected(false)
        setTransport("none")
        setError("SSE connection lost")
        es.close()
        sseRef.current = null
        // Retry SSE after 30s
        retryTimeoutRef.current = setTimeout(() => connectSSE(), 30_000)
      }
    } catch {
      setError("SSE not supported")
    }
  }, [symbols, handleQuotes])

  const connectWS = useCallback(() => {
    if (!symbols.length) return

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
    const symbolParam = symbols.join(",")
    const url = `${protocol}//${window.location.host}/api/v1/market/ws?symbols=${symbolParam}`

    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        setTransport("ws")
        setError(null)
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as RealtimeQuote[]
          handleQuotes(data)
        } catch {
          // Ignore parse errors
        }
      }

      ws.onclose = () => {
        setConnected(false)
        wsRef.current = null
        // Fall back to SSE
        setTransport("none")
        connectSSE()
      }

      ws.onerror = () => {
        ws.close()
      }
    } catch {
      // WebSocket not available, fall back to SSE
      connectSSE()
    }
  }, [symbols, handleQuotes, connectSSE])

  useEffect(() => {
    connectWS()
    return () => {
      wsRef.current?.close()
      wsRef.current = null
      sseRef.current?.close()
      sseRef.current = null
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current)
      }
    }
  }, [connectWS])

  return {
    quotes,
    connected,
    transport,
    error,
    quotesArray: Array.from(quotes.values()),
  }
}
