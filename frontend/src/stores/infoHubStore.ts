/** v21.0 Intelligence Hub store — Zustand filter state for info feed. */

import { create } from "zustand"
import type { InfoCategory, InfoPriority } from "@/types/info-hub"

type SortBy = "time" | "score"
type DiversityStrength = "low" | "medium" | "high"

interface InfoHubState {
  // Current sub-page category filter (undefined = all)
  activeCategory: InfoCategory | undefined

  // Search and priority filter
  searchQuery: string
  priorityFilter: InfoPriority | undefined

  // Sort order
  sortBy: SortBy

  // Bookmarked-only mode
  bookmarkedOnly: boolean

  // Show only items related to portfolio/watchlist symbols
  relevanceOnly: boolean

  // Intelligence preferences
  diversityStrength: DiversityStrength
  userDomains: string[]
  disabledSources: string[]

  // New item IDs from latest refresh (for "新" badge)
  newItemIds: Set<string>

  // Actions
  setActiveCategory: (category: InfoCategory | undefined) => void
  setSearchQuery: (query: string) => void
  setPriorityFilter: (priority: InfoPriority | undefined) => void
  setSortBy: (sortBy: SortBy) => void
  setBookmarkedOnly: (value: boolean) => void
  setRelevanceOnly: (value: boolean) => void
  resetFilters: () => void

  // Intelligence preference actions
  setDiversityStrength: (s: DiversityStrength) => void
  setUserDomains: (d: string[]) => void
  toggleSourceEnabled: (sourceId: string) => void

  // New items actions
  setNewItemIds: (ids: Set<string>) => void
  clearNewItemIds: () => void
}

export const useInfoHubStore = create<InfoHubState>((set) => ({
  activeCategory: undefined,
  searchQuery: "",
  priorityFilter: undefined,
  sortBy: "time",
  bookmarkedOnly: false,
  relevanceOnly: false,

  // Intelligence preferences defaults
  diversityStrength: "medium",
  userDomains: [],
  disabledSources: [],

  // New items from refresh
  newItemIds: new Set<string>(),

  setActiveCategory: (category) => set({ activeCategory: category }),
  setSearchQuery: (query) => set({ searchQuery: query }),
  setPriorityFilter: (priority) => set({ priorityFilter: priority }),
  setSortBy: (sortBy) => set({ sortBy }),
  setBookmarkedOnly: (value) => set({ bookmarkedOnly: value }),
  setRelevanceOnly: (value) => set({ relevanceOnly: value }),
  resetFilters: () =>
    set({
      searchQuery: "",
      priorityFilter: undefined,
      sortBy: "time",
      bookmarkedOnly: false,
      relevanceOnly: false,
    }),

  // Intelligence preference actions
  setDiversityStrength: (s) => set({ diversityStrength: s }),
  setUserDomains: (d) => set({ userDomains: d }),
  toggleSourceEnabled: (sourceId) =>
    set((state) => ({
      disabledSources: state.disabledSources.includes(sourceId)
        ? state.disabledSources.filter((id) => id !== sourceId)
        : [...state.disabledSources, sourceId],
    })),

  // New items actions
  setNewItemIds: (ids) => set({ newItemIds: ids }),
  clearNewItemIds: () => set({ newItemIds: new Set<string>() }),
}))
