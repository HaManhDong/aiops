"use client"
import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { apiJson } from "@/lib/api"

interface AccuracyRow {
  detector_type: string
  app_id: string
  total: number
  true_positive: number
  false_positive: number
  false_negative: number
  precision: number | null
  recall: number | null
  f1: number | null
}

export default function AccuracyReportPage() {
  const [rows, setRows] = useState<AccuracyRow[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const data = await apiJson<{ rows: AccuracyRow[] }>("/api/v1/predictions/accuracy-report")
        setRows(data.rows ?? [])
      } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi") }
      finally { setLoading(false) }
    }
    load()
  }, [])

  function fmtPct(v: number | null) {
    if (v == null) return "N/A"
    return `${(v * 100).toFixed(1)}%`
  }

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-xl font-bold">Accuracy Report</h1>
      <p className="text-sm text-muted-foreground">Đánh giá độ chính xác của Prediction Engine theo detector type và app.</p>

      {loading ? <p className="text-sm text-muted-foreground">Đang tải...</p> : (
        <div className="rounded-md border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Detector</th>
                <th className="px-3 py-2 text-left font-medium">App</th>
                <th className="px-3 py-2 text-right font-medium">Total</th>
                <th className="px-3 py-2 text-right font-medium">TP</th>
                <th className="px-3 py-2 text-right font-medium">FP</th>
                <th className="px-3 py-2 text-right font-medium">FN</th>
                <th className="px-3 py-2 text-right font-medium">Precision</th>
                <th className="px-3 py-2 text-right font-medium">Recall</th>
                <th className="px-3 py-2 text-right font-medium">F1</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t">
                  <td className="px-3 py-2 text-xs font-mono">{r.detector_type}</td>
                  <td className="px-3 py-2 text-xs">{r.app_id}</td>
                  <td className="px-3 py-2 text-right">{r.total}</td>
                  <td className="px-3 py-2 text-right text-green-600">{r.true_positive}</td>
                  <td className="px-3 py-2 text-right text-destructive">{r.false_positive}</td>
                  <td className="px-3 py-2 text-right text-yellow-600">{r.false_negative}</td>
                  <td className="px-3 py-2 text-right">{fmtPct(r.precision)}</td>
                  <td className="px-3 py-2 text-right">{fmtPct(r.recall)}</td>
                  <td className="px-3 py-2 text-right font-semibold">{fmtPct(r.f1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
