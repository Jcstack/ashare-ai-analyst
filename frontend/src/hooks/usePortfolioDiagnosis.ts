import { useMutation } from "@tanstack/react-query"
import { diagnosePortfolio, buildDiagnoseRequest } from "@/api/portfolio"
import type { PositionWithPnL } from "@/types/portfolio"

export function usePortfolioDiagnosis() {
  return useMutation({
    mutationFn: (positions: PositionWithPnL[]) => {
      const req = buildDiagnoseRequest(positions)
      return diagnosePortfolio(req)
    },
  })
}
