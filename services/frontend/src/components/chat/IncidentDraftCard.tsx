"use client"
import { useState } from "react"
import { AlertTriangle, FilePlus2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { apiJson } from "@/lib/api"
import type { IncidentDraft, IncidentRead } from "@/types/api"

interface Props { draft: IncidentDraft }

export function IncidentDraftCard({ draft }: Props) {
  const [loading, setLoading] = useState(false)
  const [created, setCreated] = useState(false)

  async function handleCreate() {
    setLoading(true)
    try {
      await apiJson<IncidentRead>("/api/v1/incidents", {
        method: "POST",
        body: JSON.stringify({
          app_id: draft.app_id,
          title: draft.title,
          severity: draft.severity,
          description: draft.description,
          incident_time: draft.incident_time,
          source: "chat_draft",
        }),
      })
      setCreated(true)
      toast.success("Đã tạo incident thành công")
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Tạo incident thất bại")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-amber-200 bg-gradient-to-br from-amber-50 to-orange-50 shadow-lg shadow-amber-200/40">
      <div className="flex items-start gap-3 p-4">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-amber-500 text-white shadow-lg shadow-amber-500/20">
          <AlertTriangle className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1 space-y-2">
          <div>
            <p className="text-sm font-semibold text-slate-950">{draft.title}</p>
            <p className="mt-1 text-xs font-medium uppercase tracking-wide text-amber-700">
              {draft.app_id} · {draft.severity} · {draft.incident_time ? new Date(draft.incident_time).toLocaleString("vi") : ""}
            </p>
          </div>
          {draft.description && <p className="line-clamp-3 text-xs leading-5 text-slate-600">{draft.description}</p>}
        </div>
        {!created ? (
          <Button size="sm" className="shrink-0 gap-1 bg-slate-950 text-white hover:bg-slate-800" disabled={loading} onClick={handleCreate}>
            <FilePlus2 className="h-3.5 w-3.5" />
            {loading ? "Đang tạo..." : "Tạo incident"}
          </Button>
        ) : (
          <span className="shrink-0 rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700">✓ Đã tạo</span>
        )}
      </div>
    </div>
  )
}
