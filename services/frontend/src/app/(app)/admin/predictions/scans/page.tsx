"use client"
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { apiJson } from "@/lib/api"
import { PaginationBar } from "@/components/admin/PaginationBar"
import { usePagination } from "@/hooks/usePagination"

interface ScanHistory {
  id: string
  app_id: string
  started_at: string
  finished_at: string | null
  status: "running" | "done" | "error"
  alerts_created: number
  duration_ms: number | null
  error_message: string | null
}

export default function ScansPage() {
  const [items, setItems] = useState<ScanHistory[]>([])
  const [loading, setLoading] = useState(true)
  const { page, setPage, pageSize, handlePageSizeChange, total, setTotal, offset } = usePagination()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ limit: String(pageSize), offset: String(offset) })
      const data = await apiJson<{ items: ScanHistory[]; total: number }>(`/api/v1/predictions/scans?${params}`)
      setItems(data.items ?? [])
      setTotal(data.total ?? 0)
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
    finally { setLoading(false) }
  }, [pageSize, offset, setTotal])

  useEffect(() => { load() }, [load])

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-xl font-bold">Scan History</h1>

      {loading ? <p className="text-sm text-muted-foreground">Đang tải...</p> : (
        <>
          <div className="rounded-md border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Bắt đầu</th>
                  <th className="px-3 py-2 text-left font-medium">App</th>
                  <th className="px-3 py-2 text-center font-medium">Status</th>
                  <th className="px-3 py-2 text-right font-medium">Alerts</th>
                  <th className="px-3 py-2 text-right font-medium hidden md:table-cell">Duration</th>
                </tr>
              </thead>
              <tbody>
                {items.map((s) => (
                  <tr key={s.id} className="border-t">
                    <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">
                      {new Date(s.started_at).toLocaleString("vi")}
                    </td>
                    <td className="px-3 py-2 text-xs font-mono">{s.app_id}</td>
                    <td className="px-3 py-2 text-center">
                      <Badge variant={s.status === "error" ? "destructive" : s.status === "running" ? "secondary" : "outline"}>
                        {s.status}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-right">{s.alerts_created}</td>
                    <td className="px-3 py-2 text-right text-xs text-muted-foreground hidden md:table-cell">
                      {s.duration_ms != null ? `${(s.duration_ms / 1000).toFixed(1)}s` : "—"}
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
