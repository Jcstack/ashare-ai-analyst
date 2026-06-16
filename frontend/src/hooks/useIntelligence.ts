/** React Query hooks for v34.0 Intelligence Agent endpoints. */

import { useQuery, useMutation } from "@tanstack/react-query"
import {
  getIntelligenceDashboard,
  getMacroCalendar,
  getEquityCurve,
  getFactorExposure,
  runDebate,
  scanRotation,
  analyzeImpactChain,
  runMungerChecklist,
} from "@/api/intelligence"

const DASHBOARD_STALE = 60 * 1000 // 1 min — macro data changes slowly

export function useIntelligenceDashboard() {
  return useQuery({
    queryKey: ["intelligence", "dashboard"],
    queryFn: getIntelligenceDashboard,
    staleTime: DASHBOARD_STALE,
    refetchInterval: 2 * 60 * 1000, // auto-refresh every 2 min
  })
}

export function useMacroCalendar(nLatest = 3) {
  return useQuery({
    queryKey: ["intelligence", "macro-calendar", nLatest],
    queryFn: () => getMacroCalendar(nLatest),
    staleTime: 5 * 60 * 1000, // 5 min — macro data is slow-moving
    refetchInterval: 10 * 60 * 1000, // auto-refresh every 10 min
  })
}

export function useEquityCurve(days = 90) {
  return useQuery({
    queryKey: ["intelligence", "equity-curve", days],
    queryFn: () => getEquityCurve(days),
    staleTime: 5 * 60 * 1000, // 5 min
    refetchInterval: 10 * 60 * 1000, // auto-refresh every 10 min
  })
}

export function useFactorExposure() {
  return useQuery({
    queryKey: ["intelligence", "factor-exposure"],
    queryFn: getFactorExposure,
    staleTime: 5 * 60 * 1000, // 5 min
    refetchInterval: 10 * 60 * 1000, // auto-refresh every 10 min
  })
}

export function useDebate() {
  return useMutation({
    mutationFn: runDebate,
  })
}

export function useRotationScan() {
  return useMutation({
    mutationFn: scanRotation,
  })
}

export function useImpactChain() {
  return useMutation({
    mutationFn: analyzeImpactChain,
  })
}

export function useMungerChecklist() {
  return useMutation({
    mutationFn: runMungerChecklist,
  })
}
