/** Mobile-only header with hamburger nav. Hidden on desktop (lg:). */

import { useCallback, useState } from "react"
import { Link, useLocation } from "react-router-dom"
import {
  Menu,
  Home,
  Briefcase,
  Settings,
  Search,
  Newspaper,
  FileBarChart,
  ChevronDown,
  Sparkles,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { MarketStatusBadge } from "./MarketStatusBadge"
import { NotificationCenter } from "./NotificationCenter"
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet"
import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"
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
  { to: "/recommendations", label: "智能选股", icon: Sparkles },
  { to: "/reports", label: "情报分析", icon: FileBarChart },
  { to: "/settings", label: "设置", icon: Settings },
]

export function MobileHeader() {
  const [open, setOpen] = useState(false)
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set())
  const location = useLocation()

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
    return location.pathname.startsWith(item.to.split("?")[0])
  }

  const isChildActive = (child: NavChild) => {
    const [childPath, childSearch] = child.to.split("?")
    if (!childSearch) {
      return location.pathname === childPath && !location.search.includes("sub=")
    }
    return location.pathname === childPath && location.search.includes(childSearch)
  }

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

  return (
    <header className="flex h-14 items-center border-b px-4 lg:hidden">
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <Button variant="ghost" size="icon">
            <Menu className="h-5 w-5" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="w-56 p-0">
          <div className="flex items-center gap-2 px-6 py-5">
            <img src="/logo.svg" alt="Logo" className="h-7 w-7 rounded-md" />
            <span className="text-lg font-bold">A股投研</span>
          </div>
          <Separator />
          <nav className="space-y-1 px-3 py-4">
            {navItems.map((item) => (
              <div key={item.to}>
                {item.children ? (
                  <>
                    <button
                      onClick={() => toggleExpand(item.to)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
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
                            onClick={() => setOpen(false)}
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
                    onClick={() => setOpen(false)}
                    className={cn(
                      "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                      isItemActive(item)
                        ? "bg-primary/8 text-primary font-semibold"
                        : "text-muted-foreground hover:bg-accent hover:text-foreground",
                    )}
                  >
                    <item.icon className="h-4 w-4" />
                    {item.label}
                  </Link>
                )}
              </div>
            ))}
          </nav>
        </SheetContent>
      </Sheet>
      <div className="ml-3 flex flex-1 items-center gap-2">
        <img src="/logo.svg" alt="Logo" className="h-5 w-5 rounded-sm" />
        <span className="font-bold">A股投研</span>
        <MarketStatusBadge compact />
      </div>
      <div className="flex items-center gap-1">
        <NotificationCenter />
        <Button
          variant="ghost"
          size="icon"
          onClick={openCommandPalette}
          className="text-muted-foreground"
        >
          <Search className="h-5 w-5" />
        </Button>
      </div>
    </header>
  )
}
