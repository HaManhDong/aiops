"use client"
import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { Plus, Search, X, TestTube2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { apiJson } from "@/lib/api"
import { DEBOUNCE_MS } from "@/lib/constants"
import type { DatasourceConfig } from "@/types/api"

const EMPTY: Partial<DatasourceConfig> = {}
type DatasourceResponse = DatasourceConfig[] | { datasources: DatasourceConfig[] }

export default function ServicesPage() {
  const [items, setItems] = useState<DatasourceConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [inputValue, setInputValue] = useState("")
  const [query, setQuery] = useState("")
  const [form, setForm] = useState<Partial<DatasourceConfig> | null>(null)
  const [testing, setTesting] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<Record<string, { ok: boolean; latency_ms: number | null; error: string | null }> | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  function handleSearch(v: string) {
    setInputValue(v)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setQuery(v), DEBOUNCE_MS)
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await apiJson<DatasourceResponse>("/api/v1/admin/services")
      const all = Array.isArray(data) ? data : data.datasources ?? []
      setItems(query ? all.filter((d) => d.display_name.toLowerCase().includes(query) || d.app_id.includes(query)) : all)
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
    finally { setLoading(false) }
  }, [query])

  useEffect(() => { load() }, [load])

  async function handleSave() {
    if (!form) return
    try {
      if (form.id) {
        await apiJson(`/api/v1/admin/services/${form.app_id}`, { method: "PUT", body: JSON.stringify(form) })
        toast.success("Đã cập nhật")
      } else {
        await apiJson("/api/v1/admin/services", { method: "POST", body: JSON.stringify(form) })
        toast.success("Đã tạo")
      }
      setForm(null)
      load()
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
  }

  async function handleTest(appId: string) {
    setTesting(appId)
    setTestResult(null)
    try {
      const data = await apiJson<{ results: Record<string, { ok: boolean; latency_ms: number | null; error: string | null }> }>(
        `/api/v1/admin/services/${appId}/test`
      )
      setTestResult(data.results)
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
    finally { setTesting(null) }
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Datasources</h1>
        <Button size="sm" onClick={() => setForm(EMPTY)}>
          <Plus className="h-4 w-4 mr-1" /> Thêm
        </Button>
      </div>

      <div className="relative max-w-xs">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input className="pl-8 pr-8" placeholder="Tìm theo tên hoặc app_id..." value={inputValue} onChange={(e) => handleSearch(e.target.value)} />
        {inputValue && (
          <button className="absolute right-2.5 top-2.5" onClick={() => { setInputValue(""); setQuery(""); if (timer.current) clearTimeout(timer.current) }}>
            <X className="h-4 w-4 text-muted-foreground" />
          </button>
        )}
      </div>

      {loading ? <p className="text-sm text-muted-foreground">Đang tải...</p> : (
        <div className="rounded-md border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-3 py-2 text-left font-medium">App ID</th>
                <th className="px-3 py-2 text-left font-medium">Tên</th>
                <th className="px-3 py-2 text-left font-medium hidden md:table-cell">ES URL</th>
                <th className="px-3 py-2 text-center font-medium">Trạng thái</th>
                <th className="px-3 py-2 text-right font-medium">Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {items.map((ds) => (
                <tr key={ds.id} className="border-t">
                  <td className="px-3 py-2 font-mono text-xs">{ds.app_id}</td>
                  <td className="px-3 py-2">{ds.display_name}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground truncate max-w-[200px] hidden md:table-cell">{ds.elasticsearch_url}</td>
                  <td className="px-3 py-2 text-center">
                    <Badge variant={ds.is_active ? "outline" : "secondary"}>{ds.is_active ? "Active" : "Inactive"}</Badge>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex gap-1 justify-end">
                      <Button size="sm" variant="outline" onClick={() => handleTest(ds.app_id)} disabled={testing === ds.app_id}>
                        <TestTube2 className="h-4 w-4" />
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => setForm(ds)}>Sửa</Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Test result */}
      {testResult && (
        <div className="rounded-md border p-3 text-sm space-y-1">
          <p className="font-medium">Kết quả test:</p>
          {Object.entries(testResult).map(([k, v]) => (
            <div key={k} className="flex items-center gap-2">
              <Badge variant={v.ok ? "outline" : "destructive"}>{k}</Badge>
              {v.ok ? <span className="text-green-600">OK ({v.latency_ms}ms)</span> : <span className="text-destructive">{v.error}</span>}
            </div>
          ))}
        </div>
      )}

      {/* Form dialog */}
      <Dialog open={!!form} onOpenChange={(o) => { if (!o) setForm(null) }}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{form?.id ? "Sửa datasource" : "Thêm datasource"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 max-h-[60vh] overflow-y-auto">
            {[
              ["app_id", "App ID *"], ["display_name", "Tên hiển thị *"],
              ["elasticsearch_url", "Elasticsearch URL *"], ["elasticsearch_api_key", "ES API Key"],
              ["app_log_index", "App Log Index *"], ["prometheus_url", "Prometheus URL"],
              ["kibana_url", "Kibana URL"], ["kibana_api_key", "Kibana API Key"],
            ].map(([key, label]) => (
              <div key={key} className="space-y-1">
                <Label className="text-xs">{label}</Label>
                <Input
                  value={(form as Record<string, string>)?.[key] ?? ""}
                  onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                  className="h-8 text-sm"
                  disabled={key === "app_id" && !!form?.id}
                />
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setForm(null)}>Hủy</Button>
            <Button onClick={handleSave}>Lưu</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
