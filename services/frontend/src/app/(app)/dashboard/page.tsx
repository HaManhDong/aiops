"use client"
import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { apiJson } from "@/lib/api"
import { AlertTriangle, Server, MessageSquare, Activity } from "lucide-react"
import Link from "next/link"
import type { IncidentRead, PredictionAlert } from "@/types/api"

interface DsHealth { app_id: string; display_name: string; is_active: boolean }
interface SessionItem { id: string; title: string | null; app_id: string | null; updated_at: string }

export default function DashboardPage() {
  const [incidents, setIncidents] = useState<IncidentRead[]>([])
  const [alerts, setAlerts] = useState<PredictionAlert[]>([])
  const [services, setServices] = useState<DsHealth[]>([])
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        await Promise.allSettled([
          apiJson<{ items: IncidentRead[]; total: number }>("/api/v1/incidents?status=open&limit=5")
            .then((d) => setIncidents(d.items)),
          apiJson<{ items: PredictionAlert[]; total: number }>("/api/v1/predictions/alerts?status=open&limit=5")
            .then((d) => setAlerts(d.items)),
          apiJson<{ datasources: DsHealth[] }>("/api/v1/admin/services")
            .then((d) => setServices(d.datasources ?? [])),
          apiJson<{ items: SessionItem[] }>("/api/v1/chat/sessions?limit=5")
            .then((d) => setSessions(d.items ?? [])),
        ])
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const criticalCount = incidents.filter((i) => i.severity === "critical").length
  const openAlerts = alerts.filter((a) => a.status === "open").length

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" /> Incidents mở
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{incidents.length}</div>
            {criticalCount > 0 && (
              <p className="text-xs text-destructive mt-1">{criticalCount} critical</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground flex items-center gap-2">
              <Activity className="h-4 w-4" /> Prediction Alerts
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{openAlerts}</div>
            <p className="text-xs text-muted-foreground mt-1">đang mở</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground flex items-center gap-2">
              <Server className="h-4 w-4" /> Services
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{services.filter((s) => s.is_active).length}</div>
            <p className="text-xs text-muted-foreground mt-1">active</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground flex items-center gap-2">
              <MessageSquare className="h-4 w-4" /> Chat Sessions
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{sessions.length}</div>
            <p className="text-xs text-muted-foreground mt-1">gần đây</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        {/* Recent Incidents */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Incidents gần đây</CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? <p className="text-sm text-muted-foreground">Đang tải...</p>
              : incidents.length === 0 ? <p className="text-sm text-muted-foreground">Không có incident</p>
              : (
                <div className="space-y-2">
                  {incidents.map((inc) => (
                    <div key={inc.id} className="flex items-center justify-between text-sm">
                      <span className="truncate flex-1">{inc.title}</span>
                      <Badge variant={inc.severity === "critical" ? "destructive" : "secondary"} className="ml-2 shrink-0">
                        {inc.severity}
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            <Link href="/admin/predictions/alerts" className="text-xs text-primary mt-3 block hover:underline">
              Xem tất cả →
            </Link>
          </CardContent>
        </Card>

        {/* Services */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Services</CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? <p className="text-sm text-muted-foreground">Đang tải...</p>
              : services.length === 0 ? <p className="text-sm text-muted-foreground">Chưa cấu hình</p>
              : (
                <div className="space-y-2">
                  {services.map((s) => (
                    <div key={s.app_id} className="flex items-center justify-between text-sm">
                      <span>{s.display_name}</span>
                      <Badge variant={s.is_active ? "outline" : "secondary"}>
                        {s.is_active ? "active" : "inactive"}
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            <Link href="/admin/services" className="text-xs text-primary mt-3 block hover:underline">
              Quản lý →
            </Link>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
