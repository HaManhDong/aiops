"use client"
import type { ReactNode } from "react"
import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Database,
  MessageSquare,
  Server,
  ShieldAlert,
  Sparkles,
  TrendingUp,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { apiJson } from "@/lib/api"
import type { IncidentRead, PredictionAlert } from "@/types/api"

interface DsHealth {
  app_id: string
  display_name: string
  is_active: boolean
  elasticsearch_url?: string | null
  prometheus_url?: string | null
}

interface SessionItem {
  id: string
  title: string | null
  app_id: string | null
  updated_at: string
}

type DatasourceResponse = DsHealth[] | { datasources: DsHealth[] }
type SessionResponse = SessionItem[] | { items: SessionItem[] }

const severityTone: Record<string, string> = {
  critical: "bg-red-50 text-red-700 border-red-200",
  high: "bg-orange-50 text-orange-700 border-orange-200",
  medium: "bg-amber-50 text-amber-700 border-amber-200",
  low: "bg-sky-50 text-sky-700 border-sky-200",
}

const serviceTone = [
  "from-orange-500 to-amber-400",
  "from-amber-500 to-yellow-400",
  "from-red-500 to-orange-500",
  "from-slate-700 to-orange-500",
]

function formatTime(value: string | null | undefined) {
  if (!value) return "Chưa rõ"
  return new Date(value).toLocaleString("vi", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })
}

function riskScore(incidents: IncidentRead[], alerts: PredictionAlert[]) {
  const incidentScore = incidents.reduce((sum, item) => {
    if (item.severity === "critical") return sum + 28
    if (item.severity === "high") return sum + 18
    if (item.severity === "medium") return sum + 10
    return sum + 4
  }, 0)
  const alertScore = alerts.reduce((sum, item) => {
    if (item.severity === "critical") return sum + 22
    if (item.severity === "high") return sum + 14
    if (item.severity === "medium") return sum + 8
    return sum + 3
  }, 0)
  return Math.min(100, incidentScore + alertScore)
}

function KpiCard({
  title,
  value,
  helper,
  icon,
  tone,
}: {
  title: string
  value: string | number
  helper: string
  icon: ReactNode
  tone: string
}) {
  return (
    <Card className="ops-card overflow-hidden rounded-xl">
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</p>
            <div className="mt-3 text-3xl font-semibold tracking-tight">{value}</div>
            <p className="mt-1 text-xs text-muted-foreground">{helper}</p>
          </div>
          <div className={`grid h-10 w-10 place-items-center rounded-lg bg-gradient-to-br ${tone} text-white shadow-lg`}>
            {icon}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export default function DashboardPage() {
  const [incidents, setIncidents] = useState<IncidentRead[]>([])
  const [alerts, setAlerts] = useState<PredictionAlert[]>([])
  const [services, setServices] = useState<DsHealth[]>([])
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        await Promise.allSettled([
          apiJson<{ items: IncidentRead[]; total: number }>("/api/v1/incidents?status=open&limit=8")
            .then((data) => setIncidents(data.items ?? [])),
          apiJson<{ items: PredictionAlert[]; total: number }>("/api/v1/predictions/alerts?status=open&limit=8")
            .then((data) => setAlerts(data.items ?? [])),
          apiJson<DatasourceResponse>("/api/v1/admin/services")
            .then((data) => setServices(Array.isArray(data) ? data : data.datasources ?? [])),
          apiJson<SessionResponse>("/api/v1/chat/sessions?limit=6")
            .then((data) => setSessions(Array.isArray(data) ? data : data.items ?? [])),
        ])
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const activeServices = services.filter((service) => service.is_active)
  const criticalIncidents = incidents.filter((incident) => incident.severity === "critical")
  const highAlerts = alerts.filter((alert) => ["critical", "high"].includes(alert.severity))
  const score = useMemo(() => riskScore(incidents, alerts), [incidents, alerts])
  const latestActivity = [
    ...incidents.slice(0, 3).map((item) => ({
      id: item.id,
      type: "Incident",
      title: item.title,
      when: item.created_at,
      tone: severityTone[item.severity] ?? severityTone.low,
    })),
    ...alerts.slice(0, 3).map((item) => ({
      id: item.id,
      type: "Prediction",
      title: item.title,
      when: item.created_at,
      tone: severityTone[item.severity] ?? severityTone.low,
    })),
  ].sort((a, b) => new Date(b.when).getTime() - new Date(a.when).getTime()).slice(0, 5)

  return (
    <div className="space-y-6 p-6 lg:p-8">
      <section className="overflow-hidden rounded-2xl border border-slate-200/80 bg-slate-950 text-white shadow-2xl shadow-slate-900/10">
        <div className="relative p-6 lg:p-7">
          <div className="absolute inset-y-0 right-0 w-1/2 bg-[radial-gradient(circle_at_top_right,rgba(251,146,60,0.30),transparent_34rem)]" />
          <div className="relative flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/8 px-3 py-1 text-xs text-orange-100">
                <Sparkles className="h-3.5 w-3.5" />
                Operations overview
              </div>
              <h1 className="mt-4 text-3xl font-semibold tracking-tight">Dashboard điều hành</h1>
              <p className="mt-2 text-sm leading-6 text-slate-300">
                Tập trung rủi ro, incident, prediction và trạng thái datasource trong một màn để nhìn là biết hệ thống đang nóng ở đâu.
              </p>
            </div>
            <div className="grid min-w-[220px] grid-cols-2 gap-3 rounded-xl border border-white/10 bg-white/8 p-3">
              <div>
                <p className="text-[11px] uppercase tracking-wide text-slate-400">Risk score</p>
                <p className="mt-1 text-3xl font-semibold">{score}</p>
              </div>
              <div className="flex items-center justify-center">
                <div className="relative h-16 w-16 rounded-full bg-slate-800">
                  <div
                    className="absolute inset-0 rounded-full"
                    style={{ background: `conic-gradient(#fb923c ${score * 3.6}deg, rgba(148,163,184,.26) 0deg)` }}
                  />
                  <div className="absolute inset-2 grid place-items-center rounded-full bg-slate-950 text-xs text-slate-300">
                    live
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          title="Incidents mở"
          value={incidents.length}
          helper={criticalIncidents.length ? `${criticalIncidents.length} critical cần xử lý` : "không có critical"}
          icon={<ShieldAlert className="h-5 w-5" />}
          tone="from-red-500 to-orange-500"
        />
        <KpiCard
          title="Prediction alerts"
          value={alerts.length}
          helper={highAlerts.length ? `${highAlerts.length} high/critical` : "tín hiệu ổn định"}
          icon={<TrendingUp className="h-5 w-5" />}
          tone="from-violet-500 to-indigo-500"
        />
        <KpiCard
          title="Services active"
          value={`${activeServices.length}/${services.length || 0}`}
          helper="datasource đang theo dõi"
          icon={<Database className="h-5 w-5" />}
          tone="from-orange-500 to-amber-400"
        />
        <KpiCard
          title="Chat sessions"
          value={sessions.length}
          helper="cuộc hội thoại gần đây"
          icon={<MessageSquare className="h-5 w-5" />}
          tone="from-sky-500 to-blue-500"
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_.85fr]">
        <Card className="ops-card rounded-xl">
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
            <CardTitle className="text-base">Service health</CardTitle>
            <Link href="/admin/services" className="inline-flex items-center gap-1 text-xs font-medium text-primary">
              Quản lý <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </CardHeader>
          <CardContent className="space-y-3">
            {loading ? (
              <p className="text-sm text-muted-foreground">Đang tải...</p>
            ) : services.length === 0 ? (
              <p className="rounded-lg bg-muted p-4 text-sm text-muted-foreground">Chưa có datasource. Seed demo sẽ làm màn này sống dậy.</p>
            ) : (
              services.slice(0, 5).map((service, index) => (
                <div key={service.app_id} className="ops-panel rounded-xl p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <div className={`h-10 w-1.5 rounded-full bg-gradient-to-b ${serviceTone[index % serviceTone.length]}`} />
                      <div>
                        <div className="flex items-center gap-2">
                          <p className="font-medium">{service.display_name}</p>
                          <Badge variant="outline" className="border-slate-300 bg-white/70 text-[11px]">
                            {service.app_id}
                          </Badge>
                        </div>
                        <p className="mt-1 max-w-[420px] truncate text-xs text-muted-foreground">
                          {service.elasticsearch_url ?? "Elasticsearch chưa cấu hình"} · {service.prometheus_url ?? "Prometheus chưa cấu hình"}
                        </p>
                      </div>
                    </div>
                    <Badge className={service.is_active ? "border-orange-200 bg-orange-50 text-orange-700" : "border-slate-200 bg-slate-100 text-slate-600"} variant="outline">
                      {service.is_active ? "healthy" : "inactive"}
                    </Badge>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card className="ops-card rounded-xl">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Prediction risk</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {loading ? (
              <p className="text-sm text-muted-foreground">Đang tải...</p>
            ) : alerts.length === 0 ? (
              <p className="rounded-lg bg-muted p-4 text-sm text-muted-foreground">Không có prediction alert đang mở.</p>
            ) : (
              alerts.slice(0, 5).map((alert) => (
                <div key={alert.id} className="rounded-xl border bg-white/82 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium leading-5">{alert.title}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {alert.app_id} · {alert.server_ip ?? "all servers"} · confidence {Math.round((alert.confidence ?? 0) * 100)}%
                      </p>
                    </div>
                    <Badge variant="outline" className={severityTone[alert.severity] ?? severityTone.low}>
                      {alert.severity}
                    </Badge>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-[.95fr_1.05fr]">
        <Card className="ops-card rounded-xl">
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
            <CardTitle className="text-base">Incident queue</CardTitle>
            <Link href="/incidents" className="inline-flex items-center gap-1 text-xs font-medium text-primary">
              Xem tất cả <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </CardHeader>
          <CardContent className="space-y-3">
            {loading ? (
              <p className="text-sm text-muted-foreground">Đang tải...</p>
            ) : incidents.length === 0 ? (
              <p className="rounded-lg bg-muted p-4 text-sm text-muted-foreground">Không có incident mở.</p>
            ) : (
              incidents.slice(0, 6).map((incident) => (
                <div key={incident.id} className="flex items-center gap-3 rounded-xl border bg-white/82 p-3">
                  <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-red-50 text-red-600">
                    <AlertTriangle className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{incident.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {incident.app_id} · {formatTime(incident.created_at)}
                    </p>
                  </div>
                  <Badge variant="outline" className={severityTone[incident.severity] ?? severityTone.low}>
                    {incident.severity}
                  </Badge>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card className="ops-card rounded-xl">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Activity stream</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {latestActivity.length === 0 ? (
                <p className="rounded-lg bg-muted p-4 text-sm text-muted-foreground">Chưa có hoạt động gần đây.</p>
              ) : (
                latestActivity.map((item) => (
                  <div key={`${item.type}-${item.id}`} className="flex gap-3">
                    <div className="mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-slate-900 text-white">
                      {item.type === "Incident" ? <Server className="h-4 w-4" /> : <Activity className="h-4 w-4" />}
                    </div>
                    <div className="min-w-0 flex-1 border-b pb-3">
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className={item.tone}>{item.type}</Badge>
                        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                          <Clock3 className="h-3 w-3" /> {formatTime(item.when)}
                        </span>
                      </div>
                      <p className="mt-1 truncate text-sm font-medium">{item.title}</p>
                    </div>
                  </div>
                ))
              )}
              {sessions.length > 0 && (
                <div className="rounded-xl border border-orange-200 bg-orange-50/80 p-3">
                  <div className="flex items-center gap-2 text-sm font-medium text-orange-900">
                    <CheckCircle2 className="h-4 w-4" />
                    {sessions[0].title ?? "Phiên chat gần nhất"} đang sẵn sàng để tiếp tục
                  </div>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
