"use client"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import {
  MessageSquare, LayoutDashboard, Server, Settings,
  LogOut, ChevronDown, ChevronRight, Activity,
  Users, Database, Map, BellRing, ClipboardList,
  TrendingUp, AlertTriangle, BarChart2, LineChart, History,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/auth"
import { Button } from "@/components/ui/button"
import { useState } from "react"

interface NavItem {
  label: string
  href?: string
  icon: React.ReactNode
  children?: NavItem[]
  adminOnly?: boolean
}

function NavLink({ item, depth = 0 }: { item: NavItem; depth?: number }) {
  const pathname = usePathname()
  const [open, setOpen] = useState(false)
  const isActive = item.href ? pathname.startsWith(item.href) : false

  if (item.children) {
    return (
      <div>
        <button
          onClick={() => setOpen((v) => !v)}
          className={cn(
            "flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
            "hover:bg-muted text-muted-foreground",
            depth > 0 && "pl-8"
          )}
        >
          {item.icon}
          <span className="flex-1 text-left">{item.label}</span>
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </button>
        {open && (
          <div className="ml-2 border-l pl-2">
            {item.children.map((child) => (
              <NavLink key={child.label} item={child} depth={depth + 1} />
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <Link
      href={item.href!}
      className={cn(
        "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
        isActive
          ? "bg-primary text-primary-foreground"
          : "hover:bg-muted text-muted-foreground",
        depth > 0 && "pl-8"
      )}
    >
      {item.icon}
      {item.label}
    </Link>
  )
}

export function Sidebar() {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const clear = useAuthStore((s) => s.clear)
  const isAdmin = user?.role === "admin"

  function handleLogout() {
    clear()
    router.replace("/login")
  }

  const navItems: NavItem[] = [
    { label: "Dashboard", href: "/dashboard", icon: <LayoutDashboard className="h-4 w-4" /> },
    { label: "Chat", href: "/chat", icon: <MessageSquare className="h-4 w-4" /> },
    ...(isAdmin
      ? [
          {
            label: "Admin",
            icon: <Settings className="h-4 w-4" />,
            adminOnly: true,
            children: [
              { label: "Datasources", href: "/admin/services", icon: <Database className="h-4 w-4" /> },
              { label: "Servers", href: "/admin/servers", icon: <Server className="h-4 w-4" /> },
              { label: "Topology", href: "/admin/topology", icon: <Map className="h-4 w-4" /> },
              { label: "Users", href: "/admin/users", icon: <Users className="h-4 w-4" /> },
              { label: "LLM Config", href: "/admin/llm-config", icon: <Activity className="h-4 w-4" /> },
              { label: "Notifications", href: "/admin/alerts", icon: <BellRing className="h-4 w-4" /> },
              { label: "Audit Logs", href: "/admin/audit-logs", icon: <ClipboardList className="h-4 w-4" /> },
            ],
          },
          {
            label: "Predictions",
            icon: <TrendingUp className="h-4 w-4" />,
            adminOnly: true,
            children: [
              { label: "Overview", href: "/admin/predictions/overview", icon: <BarChart2 className="h-4 w-4" /> },
              { label: "Alerts", href: "/admin/predictions/alerts", icon: <AlertTriangle className="h-4 w-4" /> },
              { label: "Accuracy", href: "/admin/predictions/accuracy-report", icon: <LineChart className="h-4 w-4" /> },
              { label: "Baselines", href: "/admin/predictions/baselines", icon: <Activity className="h-4 w-4" /> },
              { label: "Scan History", href: "/admin/predictions/scans", icon: <History className="h-4 w-4" /> },
            ],
          },
        ]
      : []),
  ]

  return (
    <aside className="flex h-screen w-60 flex-col border-r bg-card">
      <div className="flex h-14 items-center border-b px-4">
        <span className="font-semibold text-sm">VST AI OpsAI</span>
      </div>
      <nav className="flex-1 overflow-y-auto p-2 space-y-1">
        {navItems.map((item) => (
          <NavLink key={item.label} item={item} />
        ))}
      </nav>
      <div className="border-t p-2">
        <div className="px-3 py-1 text-xs text-muted-foreground truncate">
          {user?.full_name ?? user?.username} · {user?.role}
        </div>
        <Button variant="ghost" size="sm" className="w-full justify-start gap-2 text-muted-foreground" onClick={handleLogout}>
          <LogOut className="h-4 w-4" />
          Đăng xuất
        </Button>
      </div>
    </aside>
  )
}
