"use client"
import { useEffect, useState, use } from "react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { apiJson } from "@/lib/api"
import { useRouter } from "next/navigation"
import type { PredictionAlert } from "@/types/api"

interface BlastRadiusNode { node_id: string; label: string; risk_score: number; depth: number }
interface BlastRadius { origin: string; nodes: BlastRadiusNode[]; edges: { source: string; target: string }[] }

export default function PredictionAlertDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const [alert, setAlert] = useState<PredictionAlert | null>(null)
  const [blast, setBlast] = useState<BlastRadius | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const [a, b] = await Promise.allSettled([
          apiJson<PredictionAlert>(`/api/v1/predictions/alerts/${id}`),
          apiJson<BlastRadius>(`/api/v1/predictions/alerts/${id}/blast-radius`),
        ])
        if (a.status === "fulfilled") setAlert(a.value)
        if (b.status === "fulfilled") setBlast(b.value)
      } catch { /* ignore */ }
      finally { setLoading(false) }
    }
    load()
  }, [id])

  async function handleAcknowledge() {
    try {
      await apiJson(`/api/v1/predictions/alerts/${id}/acknowledge`, { method: "POST" })
      toast.success("Đã acknowledge")
      setAlert((a) => a ? { ...a, status: "acknowledged" } : a)
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
  }

  if (loading) return <div className="p-6 text-sm text-muted-foreground">Đang tải...</div>
  if (!alert) return <div className="p-6 text-sm text-destructive">Alert không tồn tại</div>

  return (
    <div className="p-6 space-y-6 max-w-4xl">
      <div className="flex items-center gap-2">
        <Button size="sm" variant="ghost" onClick={() => router.back()}>← Quay lại</Button>
        <h1 className="text-xl font-bold flex-1">Chi tiết Prediction Alert</h1>
        {alert.status === "open" && (
          <Button size="sm" onClick={handleAcknowledge}>Acknowledge</Button>
        )}
      </div>

      <Card>
        <CardHeader><CardTitle className="text-sm">Alert Info</CardTitle></CardHeader>
        <CardContent className="grid grid-cols-2 gap-4 text-sm">
          <div><span className="text-muted-foreground">App:</span> <span className="font-mono ml-2">{alert.app_id}</span></div>
          <div><span className="text-muted-foreground">Detector:</span> <span className="ml-2">{alert.alert_type}</span></div>
          <div><span className="text-muted-foreground">Severity:</span>
            <Badge variant={alert.severity === "critical" ? "destructive" : "secondary"} className="ml-2">{alert.severity}</Badge>
          </div>
          <div><span className="text-muted-foreground">Status:</span>
            <Badge variant="outline" className="ml-2">{alert.status}</Badge>
          </div>
          <div><span className="text-muted-foreground">Detected:</span> <span className="ml-2">{new Date(alert.created_at).toLocaleString("vi")}</span></div>
          {alert.predicted_at && (
            <div><span className="text-muted-foreground">Predicted for:</span> <span className="ml-2">{new Date(alert.predicted_at).toLocaleString("vi")}</span></div>
          )}
          {alert.confidence != null && (
            <div><span className="text-muted-foreground">Confidence:</span> <span className="ml-2">{(alert.confidence * 100).toFixed(0)}%</span></div>
          )}
        </CardContent>
      </Card>

      {alert.explanation && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Summary</CardTitle></CardHeader>
          <CardContent><p className="text-sm">{alert.explanation}</p></CardContent>
        </Card>
      )}

      {blast && blast.nodes.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Blast Radius ({blast.nodes.length} nodes)</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-2">
              {[...blast.nodes].sort((a, b) => b.risk_score - a.risk_score).map((n) => (
                <div key={n.node_id} className="flex items-center gap-3">
                  <div className="w-24 shrink-0">
                    <div className="h-2 rounded bg-destructive/20 overflow-hidden">
                      <div className="h-full bg-destructive transition-all" style={{ width: `${Math.round(n.risk_score * 100)}%` }} />
                    </div>
                  </div>
                  <span className="text-sm font-mono">{n.label ?? n.node_id}</span>
                  <Badge variant="outline" className="text-xs">depth {n.depth}</Badge>
                  <span className="text-xs text-muted-foreground">{(n.risk_score * 100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
