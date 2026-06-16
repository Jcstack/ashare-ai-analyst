import { useCallback } from "react"
import { Link, useLocation } from "react-router-dom"
import {
  Home,
  Briefcase,
  Settings,
  Moon,
  Sun,
  Search,
  Newspaper,
  ChevronDown,
  FileBarChart,
  Sparkles,
  Shield,
  History,
  Brain,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { MarketStatusBadge } from "./MarketStatusBadge"
import { NotificationCenter } from "./NotificationCenter"
import { cn } from "@/lib/utils"
import { useEffect, useState } from "react"
import { useReportUnreadCount } from "@/hooks/useIntelReports"
import { useRecommendationCount } from "@/hooks/useRecommendations"
import type { LucideIcon } from "lucide-react"

interface NavChild {
  to: string
  label: string
}

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  children?: NavChild[]
}

const navItems: NavItem[] = [
  { to: "/", label: "概览", icon: Home },
  { to: "/portfolio", label: "投资管理", icon: Briefcase },
  { to: "/market", label: "市场", icon: Newspaper },
  {
    to: "/info-hub",
    label: "情报中心",
    icon: Newspaper,
    children: [
      { to: "/info-hub", label: "全部情报" },
      { to: "/info-hub?sub=policy", label: "政策法规" },
      { to: "/info-hub?sub=macro", label: "宏观经济" },
      { to: "/info-hub?sub=industry", label: "行业动态" },
      { to: "/info-hub?sub=company", label: "公司公告" },
      { to: "/info-hub?sub=market", label: "市场行情" },
      { to: "/info-hub?sub=global", label: "全球市场" },
      { to: "/info-hub?sub=sources", label: "源管理" },
    ],
  },
  { to: "/agent", label: "Agent Brain", icon: Brain },
  { to: "/cio", label: "CIO 驾驶舱", icon: Shield },
  { to: "/trades", label: "交易记录", icon: History },
  { to: "/recommendations", label: "智能选股", icon: Sparkles },
  { to: "/reports", label: "情报分析", icon: FileBarChart },
  { to: "/settings", label: "设置", icon: Settings },
]


function ReportBadge() {
  const { data: count } = useReportUnreadCount()
  if (!count) return null
  return (
    <span className="ml-auto flex h-4 min-w-4 items-center justify-center rounded-full bg-primary text-[9px] text-primary-foreground px-1">
      {count > 99 ? "99+" : count}
    </span>
  )
}

function RecBadge() {
  const { data } = useRecommendationCount()
  const count = data?.count
  if (!count) return null
  return (
    <span className="ml-auto flex h-4 min-w-4 items-center justify-center rounded-full bg-primary text-[9px] text-primary-foreground px-1">
      {count > 99 ? "99+" : count}
    </span>
  )
}

export function Sidebar() {
  const location = useLocation()
  const [dark, setDark] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("theme") !== "light"
    }
    return true
  })
  const [expandedItems, setExpandedItems] = useState<Set<string>>(() => {
    // Auto-expand if on info-hub
    const initial = new Set<string>()
    if (location.pathname.startsWith("/info-hub")) {
      initial.add("/info-hub")
    }
    return initial
  })

  useEffect(() => {
    if (dark) {
      document.documentElement.classList.remove("light")
      document.documentElement.classList.add("dark")
      localStorage.setItem("theme", "dark")
    } else {
      document.documentElement.classList.remove("dark")
      document.documentElement.classList.add("light")
      localStorage.setItem("theme", "light")
    }
  }, [dark])

  // Auto-expand when navigating to info-hub
  useEffect(() => {
    if (location.pathname.startsWith("/info-hub")) {
      setExpandedItems((prev) => new Set(prev).add("/info-hub"))
    }
  }, [location.pathname])

  const openCommandPalette = useCallback(() => {
    document.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "k",
        metaKey: true,
        bubbles: true,
      })
    )
  }, [])

  const toggleExpand = (to: string) => {
    setExpandedItems((prev) => {
      const next = new Set(prev)
      if (next.has(to)) {
        next.delete(to)
      } else {
        next.add(to)
      }
      return next
    })
  }

  const isItemActive = (item: NavItem) => {
    if (item.to === "/") return location.pathname === "/"
    return location.pathname.startsWith(item.to.split("?")[0])
  }

  const isChildActive = (child: NavChild) => {
    const [childPath, childSearch] = child.to.split("?")
    if (!childSearch) {
      // "全部情报" — active when on /info-hub with no sub param
      return location.pathname === childPath && !location.search.includes("sub=")
    }
    return location.pathname === childPath && location.search.includes(childSearch)
  }

  return (
    <aside className="flex h-screen w-full flex-col border-r bg-sidebar">
      <div className="flex items-center gap-2 px-6 py-5">
        <img src="/logo.svg" alt="Logo" className="h-7 w-7 rounded-md" />
        <span className="text-lg font-bold">A股投研</span>
      </div>
      <Separator />
      <div className="px-3 pt-3 pb-1">
        <MarketStatusBadge />
      </div>
      <div className="px-3 pt-1 pb-2">
        <Button
          variant="outline"
          className="w-full justify-start gap-2 text-muted-foreground text-sm h-9 hover:bg-bg-hover"
          onClick={openCommandPalette}
        >
          <Search className="h-4 w-4" />
          <span className="flex-1 text-left">搜索股票...</span>
          <kbd className="pointer-events-none inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground">
            <span className="text-xs">&#8984;</span>K
          </kbd>
        </Button>
      </div>
      <nav className="flex-1 space-y-1 px-3 py-2 overflow-y-auto">
        {navItems.map((item) => (
          <div key={item.to}>
            {item.children ? (
              <>
                <button
                  onClick={() => toggleExpand(item.to)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all duration-200",
                    isItemActive(item)
                      ? "bg-primary/8 text-primary font-semibold"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground",
                  )}
                >
                  <item.icon className="h-4 w-4" />
                  <span className="flex-1 text-left">{item.label}</span>
                  <ChevronDown
                    className={cn(
                      "h-3.5 w-3.5 transition-transform",
                      expandedItems.has(item.to) && "rotate-180",
                    )}
                  />
                </button>
                {expandedItems.has(item.to) && (
                  <div className="ml-4 mt-0.5 space-y-0.5 border-l pl-3">
                    {item.children.map((child) => (
                      <Link
                        key={child.to}
                        to={child.to}
                        className={cn(
                          "block rounded-md px-2 py-1.5 text-xs transition-colors",
                          isChildActive(child)
                            ? "text-primary font-medium bg-primary/5"
                            : "text-muted-foreground hover:bg-accent hover:text-foreground",
                        )}
                      >
                        {child.label}
                      </Link>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <Link
                to={item.to}
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all duration-200",
                  isItemActive(item)
                    ? "bg-primary/8 text-primary font-semibold"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                <item.icon className="h-4 w-4" />
                {item.label}
                {item.to === "/recommendations" && <RecBadge />}
                {item.to === "/reports" && <ReportBadge />}
              </Link>
            )}
          </div>
        ))}
      </nav>
      <div className="border-t px-3 py-3 space-y-1">
        <div className="flex items-center justify-between px-1">
          <NotificationCenter />
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => setDark(!dark)}
          >
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </aside>
  )
}
