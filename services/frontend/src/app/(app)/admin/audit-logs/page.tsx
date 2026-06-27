"use client"
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { apiJson } from "@/lib/api"
import { PaginationBar } from "@/components/admin/PaginationBar"
import { usePagination } from "@/hooks/usePagination"
import type { AuditLog } from "@/types/api"

export default function AuditLogsPage() {
  const [items, setItems] = useState<AuditLog[]>([])
  const [loading, setLoading] = useState(true)
  const { page, setPage, pageSize, handlePageSizeChange, total, setTotal, offset } = usePagination()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ limit: String(pageSize), offset: String(offset) })
      const data = await apiJson<{ items: AuditLog[]; total: number }>(`/api/v1/admin/audit-logs?${params}`)
      setItems(data.items ?? [])
      setTotal(data.total ?? 0)
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
    finally { setLoading(false) }
  }, [pageSize, offset, setTotal])

  useEffect(() => { load() }, [load])

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-xl font-bold">Audit Logs</h1>
      {loading ? <p className="text-sm text-muted-foreground">Đang tải...</p> : (
        <>
          <div className="rounded-md border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Thời gian</th>
                  <th className="px-3 py-2 text-left font-medium">User</th>
                  <th className="px-3 py-2 text-left font-medium">Action</th>
                  <th className="px-3 py-2 text-left font-medium hidden md:table-cell">Entity</th>
                  <th className="px-3 py-2 text-left font-medium hidden md:table-cell">IP</th>
                </tr>
              </thead>
              <tbody>
                {items.map((l) => (
                  <tr key={l.id} className="border-t">
                    <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">
                      {new Date(l.created_at).toLocaleString("vi")}
                    </td>
                    <td className="px-3 py-2 text-xs font-mono">{l.user_id?.slice(0, 8) ?? "system"}</td>
                    <td className="px-3 py-2 text-xs font-mono">{l.action}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground hidden md:table-cell">
                      {l.entity_type} {l.entity_id?.slice(0, 8)}
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground hidden md:table-cell">{l.ip_address ?? "—"}</td>
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
