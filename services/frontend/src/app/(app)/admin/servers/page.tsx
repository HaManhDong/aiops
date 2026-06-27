"use client"
import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { Plus, Search, X, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { apiJson } from "@/lib/api"
import { DEBOUNCE_MS } from "@/lib/constants"
import type { ServerRegistryItem } from "@/types/api"

export default function ServersPage() {
  const [items, setItems] = useState<ServerRegistryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [inputValue, setInputValue] = useState("")
  const [query, setQuery] = useState("")
  const [deleteTarget, setDeleteTarget] = useState<ServerRegistryItem | null>(null)
  const [addOpen, setAddOpen] = useState(false)
  const [addAppId, setAddAppId] = useState("")
  const [addRows, setAddRows] = useState([{ ip: "", hostname: "", os: "" }])
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  function handleSearch(v: string) {
    setInputValue(v)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setQuery(v), DEBOUNCE_MS)
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (query) params.set("search", query)
      const data = await apiJson<{ servers: ServerRegistryItem[] }>(`/api/v1/servers?${params}`)
      setItems(data.servers ?? [])
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
    finally { setLoading(false) }
  }, [query])

  useEffect(() => { load() }, [load])

  async function handleDelete() {
    if (!deleteTarget) return
    try {
      await apiJson(`/api/v1/servers/${deleteTarget.id}`, { method: "DELETE" })
      toast.success("Đã xóa server")
      setDeleteTarget(null)
      load()
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
  }

  async function handleAdd() {
    const servers = addRows.filter((r) => r.ip && r.hostname)
    if (!servers.length || !addAppId) { toast.error("Cần app_id và ít nhất 1 server hợp lệ"); return }
    try {
      await apiJson("/api/v1/servers", { method: "POST", body: JSON.stringify({ app_id: addAppId, servers }) })
      toast.success("Đã thêm server")
      setAddOpen(false)
      setAddRows([{ ip: "", hostname: "", os: "" }])
      load()
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Server Registry</h1>
        <Button size="sm" onClick={() => setAddOpen(true)}><Plus className="h-4 w-4 mr-1" /> Thêm</Button>
      </div>

      <div className="relative max-w-xs">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input className="pl-8 pr-8" placeholder="Tìm IP, hostname..." value={inputValue} onChange={(e) => handleSearch(e.target.value)} />
        {inputValue && <button className="absolute right-2.5 top-2.5" onClick={() => { setInputValue(""); setQuery(""); }}><X className="h-4 w-4 text-muted-foreground" /></button>}
      </div>

      {loading ? <p className="text-sm text-muted-foreground">Đang tải...</p> : (
        <div className="rounded-md border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-3 py-2 text-left font-medium">IP</th>
                <th className="px-3 py-2 text-left font-medium">Hostname</th>
                <th className="px-3 py-2 text-left font-medium hidden md:table-cell">App ID</th>
                <th className="px-3 py-2 text-left font-medium hidden md:table-cell">OS</th>
                <th className="px-3 py-2 text-center font-medium">Trạng thái</th>
                <th className="px-3 py-2 text-right font-medium">Xóa</th>
              </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.id} className="border-t">
                  <td className="px-3 py-2 font-mono text-xs">{s.ip}</td>
                  <td className="px-3 py-2 font-mono text-xs">{s.hostname}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground hidden md:table-cell">{s.app_id}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground hidden md:table-cell">{s.os ?? "—"}</td>
                  <td className="px-3 py-2 text-center">
                    <Badge variant={s.is_active ? "outline" : "secondary"}>{s.is_active ? "Active" : "Inactive"}</Badge>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Button size="icon" variant="ghost" className="h-8 w-8 text-destructive" onClick={() => setDeleteTarget(s)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Delete confirm */}
      <Dialog open={!!deleteTarget} onOpenChange={(o) => { if (!o) setDeleteTarget(null) }}>
        <DialogContent>
          <DialogHeader><DialogTitle>Xóa server</DialogTitle></DialogHeader>
          <p className="text-sm">Xóa <strong>{deleteTarget?.hostname}</strong> ({deleteTarget?.ip})?</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>Hủy</Button>
            <Button variant="destructive" onClick={handleDelete}>Xóa</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add dialog */}
      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>Thêm server</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label className="text-xs">App ID *</Label>
              <Input value={addAppId} onChange={(e) => setAddAppId(e.target.value)} placeholder="erp" className="h-8 text-sm" />
            </div>
            {addRows.map((r, i) => (
              <div key={i} className="flex gap-2">
                <Input placeholder="IP *" value={r.ip} onChange={(e) => setAddRows((prev) => prev.map((x, j) => j === i ? { ...x, ip: e.target.value } : x))} className="h-8 text-sm" />
                <Input placeholder="Hostname *" value={r.hostname} onChange={(e) => setAddRows((prev) => prev.map((x, j) => j === i ? { ...x, hostname: e.target.value } : x))} className="h-8 text-sm" />
                <Input placeholder="OS" value={r.os} onChange={(e) => setAddRows((prev) => prev.map((x, j) => j === i ? { ...x, os: e.target.value } : x))} className="h-8 text-sm" />
              </div>
            ))}
            <Button size="sm" variant="outline" onClick={() => setAddRows((p) => [...p, { ip: "", hostname: "", os: "" }])}>
              <Plus className="h-4 w-4 mr-1" /> Thêm dòng
            </Button>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddOpen(false)}>Hủy</Button>
            <Button onClick={handleAdd}>Lưu</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
