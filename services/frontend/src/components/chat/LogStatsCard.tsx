"use client"
import type { ReactNode } from "react"
import { AlertTriangle, BarChart3, ExternalLink, Flame, ShieldCheck } from "lucide-react"
import type { LogStats } from "@/types/api"

interface Props { stats: LogStats; intent?: string }

const HIDE_INTENTS = new Set(["ROOT_CAUSE", "DEEP_ANALYSIS", "EXPERT_ANALYSIS"])

export function LogStatsCard({ stats, intent }: Props) {
  if (intent && HIDE_INTENTS.has(intent)) return null
  if (!stats) return null

  const levels = stats.by_level ?? []
  const topErrors = stats.top_errors ?? []
  const total = levels.reduce((sum, item) => sum + item.count, 0)
  const errorCount = levels
    .filter((item) => ["ERROR", "CRITICAL"].includes(item.level.toUpperCase()))
    .reduce((sum, item) => sum + item.count, 0)
  const warningCount = levels
    .filter((item) => ["WARN", "WARNING"].includes(item.level.toUpperCase()))
    .reduce((sum, item) => sum + item.count, 0)
  const errorPct = total ? Math.min(100, Math.round((errorCount / total) * 100)) : 0

  return (
    <div className="overflow-hidden rounded-2xl border border-orange-100 bg-white shadow-lg shadow-slate-200/50">
      <div className="flex items-center justify-between border-b border-orange-100 bg-gradient-to-r from-slate-950 to-slate-900 px-4 py-3 text-white">
        <span className="inline-flex items-center gap-2 text-sm font-semibold">
          <BarChart3 className="h-4 w-4 text-orange-300" />
          Log Intelligence
        </span>
        {stats.kibana_link && (
          <a href={stats.kibana_link} target="_blank" rel="noreferrer"
            className="flex items-center gap-1 text-xs text-orange-200 hover:underline">
            Kibana <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>

      <div className="space-y-4 p-4">
        <div className="grid gap-3 md:grid-cols-3">
          <MetricTile icon={<ShieldCheck className="h-4 w-4" />} label="Total logs" value={total.toLocaleString()} tone="bg-slate-50 text-slate-700" />
          <MetricTile icon={<AlertTriangle className="h-4 w-4" />} label="Warnings" value={warningCount.toLocaleString()} tone="bg-amber-50 text-amber-700" />
          <MetricTile icon={<Flame className="h-4 w-4" />} label="Errors" value={errorCount.toLocaleString()} tone="bg-red-50 text-red-700" />
        </div>

        {total > 0 && (
          <div>
            <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
              <span>Error ratio</span>
              <span>{errorPct}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full bg-gradient-to-r from-orange-400 to-red-500" style={{ width: `${errorPct}%` }} />
            </div>
          </div>
        )}

      {levels.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {levels.map((l) => (
            <span key={l.level} className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
              ["ERROR", "CRITICAL"].includes(l.level.toUpperCase())
                ? "bg-red-50 text-red-700 ring-1 ring-red-200"
                : ["WARNING", "WARN"].includes(l.level.toUpperCase())
                ? "bg-amber-50 text-amber-700 ring-1 ring-amber-200"
                : "bg-slate-50 text-slate-600 ring-1 ring-slate-200"
            }`}>
              {l.level}: {l.count}
            </span>
          ))}
        </div>
      )}
      {topErrors.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Top error patterns</p>
          {topErrors.slice(0, 5).map((e, i) => (
            <div key={i} className="flex items-start gap-3 rounded-xl border border-slate-100 bg-slate-50/70 p-3">
              <span className="shrink-0 rounded-lg bg-orange-100 px-2 py-1 text-xs font-bold text-orange-700">×{e.count}</span>
              <code className="break-words text-xs leading-5 text-slate-700">{e.payload.slice(0, 180)}</code>
            </div>
          ))}
        </div>
      )}
      </div>
    </div>
  )
}

function MetricTile({
  icon,
  label,
  value,
  tone,
}: {
  icon: ReactNode
  label: string
  value: string
  tone: string
}) {
  return (
    <div className={`rounded-xl p-3 ${tone}`}>
      <div className="mb-2 flex items-center gap-2 text-xs font-medium opacity-80">
        {icon}
        {label}
      </div>
      <div className="text-2xl font-semibold tracking-tight">{value}</div>
    </div>
  )
}
