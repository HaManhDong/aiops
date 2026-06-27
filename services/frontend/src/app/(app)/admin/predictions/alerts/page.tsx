"use client"
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { PaginationBar } from "@/components/admin/PaginationBar"
import { usePagination } from "@/hooks/usePagination"
import { apiJson } from "@/lib/api"
import { SEVERITY_COLORS } from "@/lib/constants"
import Link from "next/link"
import type { PredictionAlert } from "@/types/api"

const STATUSES = ["all", "open", "acknowledged", "resolved"]
const SEVERITIES = ["all", "critical", "high", "medium", "low"]

export default function PredictionAlertsPage() {
  const [items, setItems] = useState<PredictionAlert[]>([])
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState("open")
  const [severity, setSeverity] = useState("all")
  const { page, setPage, pageSize, handlePageSizeChange, total, setTotal, offset } = usePagination([status, severity])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ limit: String(pageSize), offset: String(offset) })
      if (status !== "all") params.set("status", status)
      if (severity !== "all") params.set("severity", severity)
      const data = await apiJson<{ items: PredictionAlert[]; total: number }>(`/api/v1/predictions/alerts?${params}`)
      setItems(data.items ?? [])
      setTotal(data.total ?? 0)
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
    finally { setLoading(false) }
  }, [pageSize, offset, status, severity, setTotal])

  useEffect(() => { load() }, [load])

  async function handleAcknowledge(id: string) {
    try {
      await apiJson(`/api/v1/predictions/alerts/${id}/acknowledge`, { method: "POST" })
      toast.success("Đã acknowledge")
      load()
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
  }

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-xl font-bold">Prediction Alerts</h1>

      <div className="flex gap-2 flex-wrap">
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="h-8 text-sm w-32"><SelectValue /></SelectTrigger>
          <SelectContent>{STATUSES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
        </Select>
        <Select value={severity} onValueChange={setSeverity}>
          <SelectTrigger className="h-8 text-sm w-32"><SelectValue /></SelectTrigger>
          <SelectContent>{SEVERITIES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
        </Select>
      </div>

      {loading ? <p className="text-sm text-muted-foreground">Đang tải...</p> : (
        <>
          <div className="rounded-md border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Thời gian</th>
                  <th className="px-3 py-2 text-left font-medium">App</th>
                  <th className="px-3 py-2 text-left font-medium">Detector</th>
                  <th className="px-3 py-2 text-center font-medium">Severity</th>
                  <th className="px-3 py-2 text-center font-medium">Status</th>
                  <th className="px-3 py-2 text-right font-medium">Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {items.map((a) => (
                  <tr key={a.id} className="border-t">
                    <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">
                      {new Date(a.created_at).toLocaleString("vi")}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">{a.app_id}</td>
                    <td className="px-3 py-2 text-xs">{a.alert_type}</td>
                    <td className="px-3 py-2 text-center">
                      <Badge
                        variant={a.severity === "critical" ? "destructive" : "secondary"}
                        style={{ color: SEVERITY_COLORS[a.severity] ?? undefined }}
                      >
                        {a.severity}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-center">
                      <Badge variant="outline">{a.status}</Badge>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="flex gap-1 justify-end">
                        <Link href={`/admin/predictions/alert/${a.id}`}>
                          <Button size="sm" variant="outline">Chi tiết</Button>
                        </Link>
                        {a.status === "open" && (
                          <Button size="sm" variant="ghost" onClick={() => handleAcknowledge(a.id)}>ACK</Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <PaginationBar total={total} page={page} pageSize={pageSize} onPageChange={setPage} onPageSizeChange={handlePageSizeChange} />
        </>
      )}
    </div>
  )
}
