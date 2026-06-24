import { useCallback } from "react"
import { Link, useLocation } from "react-router-dom"
import {
  Radio,
  Briefcase,
  Settings,
  Moon,
  Sun,
  Search,
  BarChart3,
  Globe,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { MarketStatusBadge } from "./MarketStatusBadge"
import { NotificationCenter } from "./NotificationCenter"
import { cn } from "@/lib/utils"
import { useEffect, useState } from "react"
import type { LucideIcon } from "lucide-react"

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
}

const navItems: NavItem[] = [
  { to: "/", label: "控制塔", icon: Radio },
  { to: "/portfolio", label: "持仓", icon: Briefcase },
  { to: "/review", label: "复盘", icon: BarChart3 },
  { to: "/ai-news", label: "AI 资讯", icon: Globe },
  { to: "/settings", label: "设置", icon: Settings },
]

export function Sidebar() {
  const location = useLocation()
  const [dark, setDark] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("theme") !== "light"
    }
    return true
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

  const openCommandPalette = useCallback(() => {
    document.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "k",
        metaKey: true,
        bubbles: true,
      })
    )
  }, [])

  const isItemActive = (item: NavItem) => {
    if (item.to === "/") return location.pathname === "/"
    return location.pathname.startsWith(item.to)
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
          <Link
            key={item.to}
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
          </Link>
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
