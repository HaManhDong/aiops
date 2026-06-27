"use client"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import {
  MessageSquare, LayoutDashboard, Server, Settings,
  LogOut, ChevronDown, ChevronRight, Activity,
  Users, Database, Map, BellRing, ClipboardList,
  TrendingUp, AlertTriangle, BarChart2, LineChart, History, Siren,
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
  const iconWrap = "grid h-7 w-7 shrink-0 place-items-center rounded-md bg-white/6 text-slate-300"

  if (item.children) {
    return (
      <div>
        <button
          onClick={() => setOpen((v) => !v)}
          className={cn(
            "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition-colors",
            "text-slate-300 hover:bg-white/8 hover:text-white",
            depth > 0 && "pl-8"
          )}
        >
          <span className={iconWrap}>{item.icon}</span>
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
        "flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition-colors",
        isActive
          ? "bg-orange-400/16 text-white ring-1 ring-orange-300/30"
          : "text-slate-300 hover:bg-white/8 hover:text-white",
        depth > 0 && "pl-8"
      )}
    >
      <span className={cn(iconWrap, isActive && "bg-orange-300/18 text-orange-200")}>{item.icon}</span>
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
    { label: "Incidents", href: "/incidents", icon: <Siren className="h-4 w-4" /> },
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
    <aside className="flex h-screen w-64 shrink-0 flex-col border-r border-slate-800/90 bg-slate-950 text-slate-100 shadow-2xl shadow-slate-950/30">
      <div className="flex h-16 items-center gap-3 border-b border-white/10 px-4">
        <div className="grid h-9 w-9 place-items-center rounded-lg bg-orange-400 text-sm font-bold text-slate-950 shadow-lg shadow-orange-500/25">
          AI
        </div>
        <div>
          <span className="block text-sm font-semibold tracking-wide">AI OpsAI</span>
          <span className="block text-[11px] text-slate-400">Operations cockpit</span>
        </div>
      </div>
      <nav className="flex-1 overflow-y-auto p-3 space-y-1">
        {navItems.map((item) => (
          <NavLink key={item.label} item={item} />
        ))}
      </nav>
      <div className="border-t border-white/10 p-3">
        <div className="mb-2 rounded-lg bg-white/6 px-3 py-2">
          <div className="truncate text-xs font-medium text-slate-100">{user?.full_name ?? user?.username}</div>
          <div className="text-[11px] uppercase tracking-wide text-orange-200">{user?.role}</div>
        </div>
        <Button variant="ghost" size="sm" className="w-full justify-start gap-2 text-slate-300 hover:bg-white/8 hover:text-white" onClick={handleLogout}>
          <LogOut className="h-4 w-4" />
          Đăng xuất
        </Button>
      </div>
    </aside>
  )
}
