"use client"
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { apiJson } from "@/lib/api"
import type { UserInfo } from "@/types/api"

export default function UsersPage() {
  const [users, setUsers] = useState<UserInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ username: "", password: "", full_name: "", role: "engineer" })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await apiJson<{ items: UserInfo[]; total: number }>("/api/v1/users?limit=100")
      setUsers(data.items ?? [])
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  async function handleCreate() {
    try {
      await apiJson("/api/v1/users", { method: "POST", body: JSON.stringify(form) })
      toast.success("Đã tạo user")
      setOpen(false)
      setForm({ username: "", password: "", full_name: "", role: "engineer" })
      load()
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Users</h1>
        <Button size="sm" onClick={() => setOpen(true)}><Plus className="h-4 w-4 mr-1" /> Thêm</Button>
      </div>

      {loading ? <p className="text-sm text-muted-foreground">Đang tải...</p> : (
        <div className="rounded-md border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Username</th>
                <th className="px-3 py-2 text-left font-medium">Họ tên</th>
                <th className="px-3 py-2 text-center font-medium">Role</th>
                <th className="px-3 py-2 text-center font-medium">Apps</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-t">
                  <td className="px-3 py-2 font-mono text-xs">{u.username}</td>
                  <td className="px-3 py-2">{u.full_name ?? "—"}</td>
                  <td className="px-3 py-2 text-center">
                    <Badge variant={u.role === "admin" ? "destructive" : "secondary"}>{u.role}</Badge>
                  </td>
                  <td className="px-3 py-2 text-center text-xs text-muted-foreground">
                    {u.allowed_apps?.join(", ") ?? "all"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Tạo user mới</DialogTitle></DialogHeader>
          <div className="space-y-3">
            {[["username", "Username *"], ["password", "Mật khẩu *"], ["full_name", "Họ tên"]].map(([k, l]) => (
              <div key={k} className="space-y-1">
                <Label className="text-xs">{l}</Label>
                <Input value={(form as Record<string, string>)[k]} type={k === "password" ? "password" : "text"}
                  onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))} className="h-8 text-sm" />
              </div>
            ))}
            <div className="space-y-1">
              <Label className="text-xs">Role</Label>
              <Select value={form.role} onValueChange={(v) => setForm((f) => ({ ...f, role: v }))}>
                <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {["admin", "engineer", "manager"].map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Hủy</Button>
            <Button onClick={handleCreate}>Tạo</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
