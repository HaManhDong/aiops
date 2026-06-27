"use client"
import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { apiJson } from "@/lib/api"
import Link from "next/link"
import type { PredictionAlert } from "@/types/api"
import { SEVERITY_COLORS } from "@/lib/constants"

interface OverviewStats {
  total_alerts_open: number
  total_alerts_today: number
  by_severity: Record<string, number>
  by_phase: Record<string, number>
  top_alerts: PredictionAlert[]
}

export default function PredictionsOverviewPage() {
  const [stats, setStats] = useState<OverviewStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const data = await apiJson<OverviewStats>("/api/v1/predictions/overview")
        setStats(data)
      } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
      finally { setLoading(false) }
    }
    load()
  }, [])

  if (loading) return <div className="p-6 text-sm text-muted-foreground">Đang tải...</div>
  if (!stats) return null

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-xl font-bold">Prediction Overview</h1>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground">Alerts đang mở</CardTitle></CardHeader>
          <CardContent><div className="text-3xl font-bold">{stats.total_alerts_open}</div></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground">Hôm nay</CardTitle></CardHeader>
          <CardContent><div className="text-3xl font-bold">{stats.total_alerts_today}</div></CardContent>
        </Card>
        {Object.entries(stats.by_severity).map(([sev, count]) => (
          <Card key={sev}>
            <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground uppercase">{sev}</CardTitle></CardHeader>
            <CardContent>
              <div className="text-3xl font-bold" style={{ color: SEVERITY_COLORS[sev] ?? undefined }}>{count}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {Object.keys(stats.by_phase).length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Alerts by Phase</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {Object.entries(stats.by_phase).map(([phase, count]) => (
              <Badge key={phase} variant="outline">{phase}: {count}</Badge>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle className="text-sm">Top Prediction Alerts</CardTitle></CardHeader>
        <CardContent>
          {stats.top_alerts.length === 0 ? (
            <p className="text-sm text-muted-foreground">Không có alert</p>
          ) : (
            <div className="space-y-2">
              {stats.top_alerts.map((a) => (
                <div key={a.id} className="flex items-center justify-between text-sm">
                  <Link href={`/admin/predictions/alert/${a.id}`} className="hover:underline truncate flex-1">
                    {a.app_id.toUpperCase()} — {a.alert_type}
                  </Link>
                  <div className="flex gap-2 ml-2 shrink-0">
                    <Badge variant={a.severity === "critical" ? "destructive" : "secondary"}>{a.severity}</Badge>
                    <Badge variant="outline">{a.status}</Badge>
                  </div>
                </div>
              ))}
            </div>
          )}
          <Link href="/admin/predictions/alerts" className="text-xs text-primary mt-3 block hover:underline">Xem tất cả →</Link>
        </CardContent>
      </Card>
    </div>
  )
}
