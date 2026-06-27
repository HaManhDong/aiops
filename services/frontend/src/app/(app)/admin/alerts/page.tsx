"use client"
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { Plus, Trash2, Play } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { apiJson } from "@/lib/api"
import type { NotificationConfig } from "@/types/api"

const EMPTY_FORM = { name: "", channel: "email" as "email" | "telegram", schedule_cron: "0 8 * * *", recipients: "", report_window_hours: 24, app_id: "" }

export default function AlertsPage() {
  const [items, setItems] = useState<NotificationConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState<typeof EMPTY_FORM | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<NotificationConfig | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await apiJson<NotificationConfig[]>("/api/v1/notifications")
      setItems(data ?? [])
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  async function handleSave() {
    if (!form) return
    const payload = {
      ...form,
      recipients: form.recipients.split(",").map((r) => r.trim()).filter(Boolean),
    }
    try {
      await apiJson("/api/v1/notifications", { method: "POST", body: JSON.stringify(payload) })
      toast.success("Đã tạo notification config")
      setForm(null)
      load()
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
  }

  async function handleDelete() {
    if (!deleteTarget) return
    try {
      await apiJson(`/api/v1/notifications/${deleteTarget.id}`, { method: "DELETE" })
      toast.success("Đã xóa")
      setDeleteTarget(null)
      load()
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
  }

  async function handleTrigger(id: string) {
    try {
      await apiJson(`/api/v1/notifications/${id}/trigger`, { method: "POST" })
      toast.success("Đang gửi báo cáo...")
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Notification Configs</h1>
        <Button size="sm" onClick={() => setForm(EMPTY_FORM)}><Plus className="h-4 w-4 mr-1" /> Thêm</Button>
      </div>

      {loading ? <p className="text-sm text-muted-foreground">Đang tải...</p> : (
        <div className="rounded-md border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Tên</th>
                <th className="px-3 py-2 text-left font-medium">Channel</th>
                <th className="px-3 py-2 text-left font-medium hidden md:table-cell">Cron</th>
                <th className="px-3 py-2 text-center font-medium">Trạng thái</th>
                <th className="px-3 py-2 text-right font-medium">Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {items.map((n) => (
                <tr key={n.id} className="border-t">
                  <td className="px-3 py-2">{n.name}</td>
                  <td className="px-3 py-2"><Badge variant="outline">{n.channel}</Badge></td>
                  <td className="px-3 py-2 text-xs font-mono text-muted-foreground hidden md:table-cell">{n.schedule_cron}</td>
                  <td className="px-3 py-2 text-center">
                    <Badge variant={n.is_enabled ? "outline" : "secondary"}>{n.is_enabled ? "Enabled" : "Disabled"}</Badge>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex gap-1 justify-end">
                      <Button size="icon" variant="ghost" className="h-8 w-8" onClick={() => handleTrigger(n.id)}><Play className="h-4 w-4" /></Button>
                      <Button size="icon" variant="ghost" className="h-8 w-8 text-destructive" onClick={() => setDeleteTarget(n)}><Trash2 className="h-4 w-4" /></Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={!!form} onOpenChange={(o) => { if (!o) setForm(null) }}>
        <DialogContent>
          <DialogHeader><DialogTitle>Tạo notification config</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label className="text-xs">Tên *</Label>
              <Input value={form?.name ?? ""} onChange={(e) => setForm((f) => f ? { ...f, name: e.target.value } : f)} className="h-8 text-sm" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Channel</Label>
              <Select value={form?.channel} onValueChange={(v) => setForm((f) => f ? { ...f, channel: v as "email" | "telegram" } : f)}>
                <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="email">Email</SelectItem><SelectItem value="telegram">Telegram</SelectItem></SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">App ID (trống = tất cả)</Label>
              <Input value={form?.app_id ?? ""} onChange={(e) => setForm((f) => f ? { ...f, app_id: e.target.value } : f)} className="h-8 text-sm" placeholder="erp" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Cron schedule</Label>
              <Input value={form?.schedule_cron ?? ""} onChange={(e) => setForm((f) => f ? { ...f, schedule_cron: e.target.value } : f)} className="h-8 text-sm font-mono" placeholder="0 8 * * *" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Recipients (cách nhau bằng dấu phẩy)</Label>
              <Input value={form?.recipients ?? ""} onChange={(e) => setForm((f) => f ? { ...f, recipients: e.target.value } : f)} className="h-8 text-sm" placeholder="admin@example.com, 123456789" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setForm(null)}>Hủy</Button>
            <Button onClick={handleSave}>Lưu</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteTarget} onOpenChange={(o) => { if (!o) setDeleteTarget(null) }}>
        <DialogContent>
          <DialogHeader><DialogTitle>Xóa notification config</DialogTitle></DialogHeader>
          <p className="text-sm">Xóa <strong>{deleteTarget?.name}</strong>?</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>Hủy</Button>
            <Button variant="destructive" onClick={handleDelete}>Xóa</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
