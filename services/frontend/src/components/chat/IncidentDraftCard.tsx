"use client"
import { useState } from "react"
import { AlertTriangle } from "lucide-react"
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
    <div className="rounded-md border border-yellow-200 bg-yellow-50 p-3 text-sm mt-2 dark:border-yellow-800 dark:bg-yellow-950">
      <div className="flex items-start gap-2">
        <AlertTriangle className="h-4 w-4 text-yellow-600 mt-0.5 shrink-0" />
        <div className="flex-1 space-y-1">
          <p className="font-medium">{draft.title}</p>
          <p className="text-xs text-muted-foreground">
            {draft.app_id.toUpperCase()} · {draft.severity.toUpperCase()} ·{" "}
            {draft.incident_time ? new Date(draft.incident_time).toLocaleString("vi") : ""}
          </p>
          {draft.description && (
            <p className="text-xs text-muted-foreground line-clamp-2">{draft.description}</p>
          )}
        </div>
        {!created ? (
          <Button size="sm" variant="outline" className="shrink-0" disabled={loading} onClick={handleCreate}>
            {loading ? "Đang tạo..." : "Tạo incident"}
          </Button>
        ) : (
          <span className="text-xs text-green-600 font-medium shrink-0">✓ Đã tạo</span>
        )}
      </div>
    </div>
  )
}
