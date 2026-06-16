import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { startConversation, sendFollowup } from "@/api/agent"
import type { IntelContext } from "@/api/agent"
import type { ConversationResponse } from "@/types/agent"

export function useAgentConversation(
  symbol: string,
  position?: { cost_price: number; shares: number; holding_days?: number },
  intelContext?: IntelContext,
) {
  const queryClient = useQueryClient()
  const queryKey = ["agent-conversation", symbol, intelContext?.item_ids?.join(",") ?? ""]

  const query = useQuery({
    queryKey,
    queryFn: () => startConversation(symbol, position, intelContext),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })

  const followupMutation = useMutation({
    mutationFn: ({ sessionId, message }: { sessionId: string; message: string }) =>
      sendFollowup(symbol, sessionId, message),
    onSuccess: (data: ConversationResponse) => {
      queryClient.setQueryData(queryKey, data)
    },
  })

  return {
    data: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
    sendFollowup: followupMutation.mutate,
    isSending: followupMutation.isPending,
    followupError: followupMutation.error,
    resetFollowupError: followupMutation.reset,
  }
}
