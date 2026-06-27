"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { AlertTriangle, CheckCircle2, FilePlus2, Search, Wrench } from "lucide-react"
import { toast } from "sonner"
import { PaginationBar } from "@/components/admin/PaginationBar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { usePagination } from "@/hooks/usePagination"
import { apiJson } from "@/lib/api"
import { STATUS_COLORS } from "@/lib/constants"
import type { IncidentRead } from "@/types/api"

const STATUSES = ["all", "open", "investigating", "resolved", "closed"]
const SEVERITIES = ["all", "critical", "high", "medium", "low"]

const severityTone: Record<string, string> = {
  critical: "border-red-200 bg-red-50 text-red-700",
  high: "border-orange-200 bg-orange-50 text-orange-700",
  medium: "border-amber-200 bg-amber-50 text-amber-700",
  low: "border-emerald-200 bg-emerald-50 text-emerald-700",
}

function formatTime(value: string | null) {
  if (!value) return "—"
  return new Date(value).toLocaleString("vi")
}

function normalizeLines(value: string) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean)
}

export default function IncidentsPage() {
  const [items, setItems] = useState<IncidentRead[]>([])
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState("open")
  const [severity, setSeverity] = useState("all")
  const [appId, setAppId] = useState("")
  const [query, setQuery] = useState("")
  const [createOpen, setCreateOpen] = useState(false)
  const [detail, setDetail] = useState<IncidentRead | null>(null)
  const [solution, setSolution] = useState("")
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({
    app_id: "openstack",
    title: "",
    severity: "high",
    description: "",
    affected_servers: "",
  })
  const { page, setPage, pageSize, handlePageSizeChange, total, setTotal, offset } = usePagination([status, severity, appId])

  const filteredItems = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    if (!keyword) return items
    return items.filter((item) =>
      [item.title, item.app_id, item.description, item.root_cause, item.solution]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword))
    )
  }, [items, query])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ limit: String(pageSize), offset: String(offset) })
      if (status !== "all") params.set("status", status)
      if (severity !== "all") params.set("severity", severity)
      if (appId.trim()) params.set("app_id", appId.trim())
      const data = await apiJson<{ items: IncidentRead[]; total: number }>(`/api/v1/incidents?${params}`)
      setItems(data.items ?? [])
      setTotal(data.total ?? 0)
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Không tải được incidents")
    } finally {
      setLoading(false)
    }
  }, [appId, offset, pageSize, setTotal, severity, status])

  useEffect(() => { load() }, [load])

  async function handleCreate() {
    if (!form.app_id.trim() || !form.title.trim()) {
      toast.error("Cần App ID và tiêu đề incident")
      return
    }
    setCreating(true)
    try {
      await apiJson<IncidentRead>("/api/v1/incidents", {
        method: "POST",
        body: JSON.stringify({
          app_id: form.app_id.trim(),
          title: form.title.trim(),
          severity: form.severity,
          description: form.description.trim() || null,
          affected_servers: normalizeLines(form.affected_servers),
          source: "manual",
        }),
      })
      toast.success("Đã tạo incident")
      setCreateOpen(false)
      setForm({ app_id: form.app_id, title: "", severity: "high", description: "", affected_servers: "" })
      load()
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Tạo incident thất bại")
    } finally {
      setCreating(false)
    }
  }

  async function updateIncident(id: string, payload: Record<string, unknown>, success: string) {
    try {
      const updated = await apiJson<IncidentRead>(`/api/v1/incidents/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      })
      toast.success(success)
      setItems((prev) => prev.map((item) => item.id === id ? updated : item))
      setDetail((current) => current?.id === id ? updated : current)
      if (payload.status === "resolved" || payload.status === "closed") load()
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Cập nhật incident thất bại")
    }
  }

  function openDetail(item: IncidentRead) {
    setDetail(item)
    setSolution(item.solution ?? "")
  }

  const openCount = items.filter((item) => item.status === "open").length
  const criticalCount = items.filter((item) => item.severity === "critical").length

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Incident Management</h1>
          <p className="text-sm text-muted-foreground">Theo dõi, điều tra và đóng vòng xử lý sự cố vận hành.</p>
        </div>
        <Button className="gap-2" onClick={() => setCreateOpen(true)}>
          <FilePlus2 className="h-4 w-4" />
          Tạo incident
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="ops-card">
          <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground">Đang mở</CardTitle></CardHeader>
          <CardContent className="text-3xl font-bold">{openCount}</CardContent>
        </Card>
        <Card className="ops-card">
          <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground">Critical</CardTitle></CardHeader>
          <CardContent className="text-3xl font-bold text-red-600">{criticalCount}</CardContent>
        </Card>
        <Card className="ops-card">
          <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground">Tổng theo filter</CardTitle></CardHeader>
          <CardContent className="text-3xl font-bold">{total}</CardContent>
        </Card>
      </div>

      <Card className="ops-card">
        <CardHeader className="gap-3 pb-3">
          <CardTitle className="text-base">Incident queue</CardTitle>
          <div className="flex flex-col gap-2 lg:flex-row">
            <div className="relative lg:w-72">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input className="pl-8" placeholder="Tìm tiêu đề, mô tả..." value={query} onChange={(event) => setQuery(event.target.value)} />
            </div>
            <Input className="lg:w-44" placeholder="Filter app_id" value={appId} onChange={(event) => setAppId(event.target.value)} />
            <Select value={status} onValueChange={setStatus}>
              <SelectTrigger className="lg:w-40"><SelectValue /></SelectTrigger>
              <SelectContent>{STATUSES.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectContent>
            </Select>
            <Select value={severity} onValueChange={setSeverity}>
              <SelectTrigger className="lg:w-40"><SelectValue /></SelectTrigger>
              <SelectContent>{SEVERITIES.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-sm text-muted-foreground">Đang tải incidents...</p>
          ) : filteredItems.length === 0 ? (
            <div className="rounded-xl border border-dashed bg-muted/50 p-8 text-center text-sm text-muted-foreground">
              Không có incident phù hợp.
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border">
              <table className="w-full text-sm">
                <thead className="bg-muted/60">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Incident</th>
                    <th className="px-3 py-2 text-left font-medium">App</th>
                    <th className="px-3 py-2 text-center font-medium">Severity</th>
                    <th className="px-3 py-2 text-center font-medium">Status</th>
                    <th className="px-3 py-2 text-left font-medium hidden lg:table-cell">Thời gian</th>
                    <th className="px-3 py-2 text-right font-medium">Thao tác</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.map((item) => (
                    <tr key={item.id} className="border-t bg-white/72">
                      <td className="min-w-0 px-3 py-3">
                        <button className="block max-w-[420px] truncate text-left font-medium hover:underline" onClick={() => openDetail(item)}>
                          {item.title}
                        </button>
                        <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">{item.description ?? item.root_cause ?? item.source}</p>
                      </td>
                      <td className="px-3 py-3 font-mono text-xs">{item.app_id}</td>
                      <td className="px-3 py-3 text-center">
                        <Badge variant="outline" className={severityTone[item.severity] ?? severityTone.low}>{item.severity}</Badge>
                      </td>
                      <td className="px-3 py-3 text-center">
                        <Badge variant={STATUS_COLORS[item.status] === "destructive" ? "destructive" : "outline"}>{item.status}</Badge>
                      </td>
                      <td className="px-3 py-3 text-xs text-muted-foreground hidden lg:table-cell">{formatTime(item.incident_time ?? item.created_at)}</td>
                      <td className="px-3 py-3 text-right">
                        <div className="flex justify-end gap-1">
                          <Button size="sm" variant="outline" onClick={() => openDetail(item)}>Chi tiết</Button>
                          {item.status === "open" && (
                            <Button size="sm" variant="ghost" onClick={() => updateIncident(item.id, { status: "investigating" }, "Đã chuyển sang investigating")}>
                              <Wrench className="h-3.5 w-3.5" />
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <PaginationBar total={total} page={page} pageSize={pageSize} onPageChange={setPage} onPageSizeChange={handlePageSizeChange} />
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader><DialogTitle>Tạo incident thủ công</DialogTitle></DialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-3 md:grid-cols-[1fr_180px]">
              <div className="space-y-1">
                <Label>App ID *</Label>
                <Input value={form.app_id} onChange={(event) => setForm((prev) => ({ ...prev, app_id: event.target.value }))} placeholder="openstack" />
              </div>
              <div className="space-y-1">
                <Label>Severity</Label>
                <Select value={form.severity} onValueChange={(value) => setForm((prev) => ({ ...prev, severity: value }))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{SEVERITIES.filter((item) => item !== "all").map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1">
              <Label>Tiêu đề *</Label>
              <Input value={form.title} onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))} placeholder="CPU spike trên controller openstack" />
            </div>
            <div className="space-y-1">
              <Label>Mô tả</Label>
              <Textarea value={form.description} onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))} rows={4} />
            </div>
            <div className="space-y-1">
              <Label>Affected servers, mỗi dòng một server/IP</Label>
              <Textarea value={form.affected_servers} onChange={(event) => setForm((prev) => ({ ...prev, affected_servers: event.target.value }))} rows={3} placeholder="192.168.1.111" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Hủy</Button>
            <Button onClick={handleCreate} disabled={creating}>{creating ? "Đang tạo..." : "Tạo incident"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!detail} onOpenChange={(open) => { if (!open) setDetail(null) }}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-orange-500" />
              {detail?.title}
            </DialogTitle>
          </DialogHeader>
          {detail && (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2">
                <Badge variant="outline">{detail.app_id}</Badge>
                <Badge variant="outline" className={severityTone[detail.severity] ?? severityTone.low}>{detail.severity}</Badge>
                <Badge variant={detail.status === "open" ? "destructive" : "outline"}>{detail.status}</Badge>
                <Badge variant="outline">{detail.source}</Badge>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <p className="text-xs font-medium uppercase text-muted-foreground">Incident time</p>
                  <p className="text-sm">{formatTime(detail.incident_time ?? detail.created_at)}</p>
                </div>
                <div>
                  <p className="text-xs font-medium uppercase text-muted-foreground">Affected servers</p>
                  <p className="text-sm">{detail.affected_servers?.join(", ") || "—"}</p>
                </div>
              </div>
              <div className="rounded-xl bg-muted/60 p-4">
                <p className="text-xs font-medium uppercase text-muted-foreground">Mô tả</p>
                <p className="mt-2 whitespace-pre-wrap text-sm">{detail.description || "Chưa có mô tả."}</p>
              </div>
              <div className="grid gap-3">
                <Label>Solution / ghi chú xử lý</Label>
                <Textarea value={solution} onChange={(event) => setSolution(event.target.value)} rows={4} placeholder="Nhập cách xử lý trước khi resolve..." />
              </div>
            </div>
          )}
          <DialogFooter className="gap-2 sm:justify-between">
            <Button variant="outline" onClick={() => setDetail(null)}>Đóng</Button>
            <div className="flex gap-2">
              {detail?.status === "open" && (
                <Button variant="outline" onClick={() => updateIncident(detail.id, { status: "investigating" }, "Đã nhận xử lý incident")}>
                  Investigating
                </Button>
              )}
              {detail && detail.status !== "resolved" && detail.status !== "closed" && (
                <Button
                  className="gap-2"
                  onClick={() => updateIncident(detail.id, { status: "resolved", solution: solution.trim() }, "Đã resolve incident")}
                  disabled={!solution.trim()}
                >
                  <CheckCircle2 className="h-4 w-4" />
                  Resolve
                </Button>
              )}
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
