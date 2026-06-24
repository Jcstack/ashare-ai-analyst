/** Mobile-only header with hamburger nav. Hidden on desktop (lg:). */

import { useCallback, useState } from "react"
import { Link, useLocation } from "react-router-dom"
import {
  Menu,
  Radio,
  Briefcase,
  Settings,
  Search,
  BarChart3,
  Globe,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { MarketStatusBadge } from "./MarketStatusBadge"
import { NotificationCenter } from "./NotificationCenter"
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet"
import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"
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

export function MobileHeader() {
  const [open, setOpen] = useState(false)
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
    return location.pathname.startsWith(item.to)
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
              <Link
                key={item.to}
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
