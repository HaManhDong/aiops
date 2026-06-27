"use client"
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { apiJson } from "@/lib/api"
import { PaginationBar } from "@/components/admin/PaginationBar"
import { usePagination } from "@/hooks/usePagination"

interface Baseline {
  id: string
  app_id: string
  host: string
  metric_name: string
  mean: number
  std: number
  ewma: number | null
  updated_at: string
}

export default function BaselinesPage() {
  const [items, setItems] = useState<Baseline[]>([])
  const [loading, setLoading] = useState(true)
  const [appId, setAppId] = useState("all")
  const { page, setPage, pageSize, handlePageSizeChange, total, setTotal, offset } = usePagination([appId])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ limit: String(pageSize), offset: String(offset) })
      if (appId !== "all") params.set("app_id", appId)
      const data = await apiJson<{ items: Baseline[]; total: number }>(`/api/v1/predictions/baselines?${params}`)
      setItems(data.items ?? [])
      setTotal(data.total ?? 0)
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
    finally { setLoading(false) }
  }, [pageSize, offset, appId, setTotal])

  useEffect(() => { load() }, [load])

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-xl font-bold">Baselines</h1>

      <div className="flex gap-2">
        <Select value={appId} onValueChange={setAppId}>
          <SelectTrigger className="h-8 text-sm w-40"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Tất cả</SelectItem>
            <SelectItem value="erp">ERP</SelectItem>
            <SelectItem value="crm">CRM</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {loading ? <p className="text-sm text-muted-foreground">Đang tải...</p> : (
        <>
          <div className="rounded-md border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">App</th>
                  <th className="px-3 py-2 text-left font-medium">Host</th>
                  <th className="px-3 py-2 text-left font-medium">Metric</th>
                  <th className="px-3 py-2 text-right font-medium">Mean</th>
                  <th className="px-3 py-2 text-right font-medium">Std</th>
                  <th className="px-3 py-2 text-right font-medium hidden md:table-cell">EWMA</th>
                  <th className="px-3 py-2 text-right font-medium hidden md:table-cell">Updated</th>
                </tr>
              </thead>
              <tbody>
                {items.map((b) => (
                  <tr key={b.id} className="border-t">
                    <td className="px-3 py-2 text-xs font-mono">{b.app_id}</td>
                    <td className="px-3 py-2 text-xs font-mono">{b.host}</td>
                    <td className="px-3 py-2 text-xs">{b.metric_name}</td>
                    <td className="px-3 py-2 text-right text-xs">{b.mean.toFixed(2)}</td>
                    <td className="px-3 py-2 text-right text-xs">{b.std.toFixed(2)}</td>
                    <td className="px-3 py-2 text-right text-xs hidden md:table-cell">{b.ewma?.toFixed(2) ?? "N/A"}</td>
                    <td className="px-3 py-2 text-right text-xs text-muted-foreground hidden md:table-cell">
                      {new Date(b.updated_at).toLocaleDateString("vi")}
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
