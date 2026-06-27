"use client"
import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Progress } from "@/components/ui/progress"
import { Separator } from "@/components/ui/separator"
import { apiJson, apiFetch } from "@/lib/api"
import { readSSEStream } from "@/lib/sse"

interface ProviderConfig {
  provider: string
  base_url: string
  model: string
  api_key?: string
  temperature: number
  max_tokens: number
  stream: boolean
}

const PROVIDERS = ["openai_compatible", "ollama", "openai", "azure_openai"]

export default function LLMConfigPage() {
  const [config, setConfig] = useState<ProviderConfig | null>(null)
  const [draft, setDraft] = useState<ProviderConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [testResult, setTestResult] = useState<string | null>(null)
  const [testing, setTesting] = useState(false)

  // Ollama pull
  const [pullModel, setPullModel] = useState("")
  const [pulling, setPulling] = useState(false)
  const [pullProgress, setPullProgress] = useState<number | null>(null)
  const [pullStatus, setPullStatus] = useState<string | null>(null)
  const abortRef = useRef<(() => void) | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await apiJson<ProviderConfig>("/api/v1/admin/llm-config")
      setConfig(data)
      setDraft({ ...data })
      if (data.provider === "ollama") setPullModel(data.model ?? "")
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi tải config") }
  }, [])

  useEffect(() => { load() }, [load])

  async function handleSave() {
    if (!draft) return
    setSaving(true)
    try {
      await apiJson("/api/v1/admin/llm-config", { method: "PUT", body: JSON.stringify(draft) })
      toast.success("Đã lưu LLM config")
      load()
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
    finally { setSaving(false) }
  }

  async function handleTest() {
    setTesting(true)
    setTestResult(null)
    try {
      const data = await apiJson<{ ok: boolean; latency_ms: number; error: string | null }>("/api/v1/admin/llm-config/test")
      setTestResult(data.ok ? `✓ OK (${data.latency_ms}ms)` : `✗ ${data.error}`)
    } catch (err: unknown) { setTestResult(`✗ ${err instanceof Error ? err.message : "Lỗi"}`) }
    finally { setTesting(false) }
  }

  async function handlePull() {
    if (!pullModel.trim()) return
    setPulling(true)
    setPullProgress(0)
    setPullStatus("Đang kết nối...")
    let cancelled = false
    abortRef.current = () => { cancelled = true; setPulling(false) }

    try {
      const res = await apiFetch(`/api/v1/admin/llm-config/ollama/pull`, {
        method: "POST",
        body: JSON.stringify({ model: pullModel.trim() }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      for await (const { data } of readSSEStream(res)) {
        if (cancelled) break
        const d = data as Record<string, unknown>
        if (d.status) setPullStatus(d.status as string)
        if (d.total != null && d.completed != null) {
          setPullProgress(Math.round(((d.completed as number) / (d.total as number)) * 100))
        }
        if (d.done) {
          setPullProgress(100)
          setPullStatus("Hoàn thành!")
          toast.success(`Đã pull model ${pullModel}`)
          break
        }
      }
    } catch (err: unknown) {
      if (!cancelled) toast.error(err instanceof Error ? err.message : "Pull thất bại")
    } finally {
      if (!cancelled) setPulling(false)
    }
  }

  if (!draft) return <div className="p-6 text-sm text-muted-foreground">Đang tải...</div>

  return (
    <div className="p-6 space-y-6 max-w-2xl">
      <h1 className="text-xl font-bold">LLM Configuration</h1>

      <Card>
        <CardHeader><CardTitle className="text-sm">Provider Settings</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <Label className="text-xs">Provider</Label>
              <Select value={draft.provider} onValueChange={(v) => setDraft((d) => d ? { ...d, provider: v } : d)}>
                <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {PROVIDERS.map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Model</Label>
              <Input value={draft.model ?? ""} onChange={(e) => setDraft((d) => d ? { ...d, model: e.target.value } : d)} className="h-8 text-sm" placeholder="qwen2.5:14b" />
            </div>
          </div>

          <div className="space-y-1">
            <Label className="text-xs">Base URL</Label>
            <Input value={draft.base_url ?? ""} onChange={(e) => setDraft((d) => d ? { ...d, base_url: e.target.value } : d)} className="h-8 text-sm font-mono" placeholder="http://localhost:11434" />
          </div>

          <div className="space-y-1">
            <Label className="text-xs">API Key (để trống nếu không cần)</Label>
            <Input type="password" value={draft.api_key ?? ""} onChange={(e) => setDraft((d) => d ? { ...d, api_key: e.target.value } : d)} className="h-8 text-sm" />
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-1">
              <Label className="text-xs">Temperature</Label>
              <Input type="number" step="0.1" min="0" max="2" value={draft.temperature} onChange={(e) => setDraft((d) => d ? { ...d, temperature: parseFloat(e.target.value) } : d)} className="h-8 text-sm" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Max Tokens</Label>
              <Input type="number" value={draft.max_tokens} onChange={(e) => setDraft((d) => d ? { ...d, max_tokens: parseInt(e.target.value) } : d)} className="h-8 text-sm" />
            </div>
          </div>

          <div className="flex gap-2 pt-2">
            <Button size="sm" onClick={handleSave} disabled={saving}>{saving ? "Đang lưu..." : "Lưu"}</Button>
            <Button size="sm" variant="outline" onClick={handleTest} disabled={testing}>{testing ? "Đang test..." : "Test kết nối"}</Button>
            {testResult && (
              <span className={`text-sm self-center ${testResult.startsWith("✓") ? "text-green-600" : "text-destructive"}`}>{testResult}</span>
            )}
          </div>
        </CardContent>
      </Card>

      {(config?.provider === "ollama" || draft.provider === "ollama") && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Ollama Model Pull</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="flex gap-2">
              <Input value={pullModel} onChange={(e) => setPullModel(e.target.value)} placeholder="qwen2.5:14b" className="h-8 text-sm font-mono" />
              <Button size="sm" onClick={handlePull} disabled={pulling || !pullModel.trim()}>
                {pulling ? "Đang pull..." : "Pull"}
              </Button>
              {pulling && (
                <Button size="sm" variant="outline" onClick={() => abortRef.current?.()}>Hủy</Button>
              )}
            </div>
            {pulling && (
              <div className="space-y-1">
                <Progress value={pullProgress ?? 0} className="h-2" />
                <p className="text-xs text-muted-foreground">{pullStatus}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
