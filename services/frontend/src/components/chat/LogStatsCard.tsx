"use client"
import { ExternalLink } from "lucide-react"
import type { LogStats } from "@/types/api"

interface Props { stats: LogStats; intent?: string }

const HIDE_INTENTS = new Set(["ROOT_CAUSE", "DEEP_ANALYSIS", "EXPERT_ANALYSIS"])

export function LogStatsCard({ stats, intent }: Props) {
  if (intent && HIDE_INTENTS.has(intent)) return null
  if (!stats) return null

  const levels = stats.by_level ?? []
  const topErrors = stats.top_errors ?? []

  return (
    <div className="rounded-md border p-3 text-sm mt-2 space-y-2">
      <div className="flex items-center justify-between">
        <span className="font-medium text-xs uppercase tracking-wide text-muted-foreground">Log Stats</span>
        {stats.kibana_link && (
          <a href={stats.kibana_link} target="_blank" rel="noreferrer"
            className="flex items-center gap-1 text-xs text-primary hover:underline">
            Kibana <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
      {levels.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {levels.map((l) => (
            <span key={l.level} className={`rounded px-2 py-0.5 text-xs font-mono ${
              l.level === "ERROR" || l.level === "CRITICAL"
                ? "bg-destructive/10 text-destructive"
                : l.level === "WARNING" || l.level === "WARN"
                ? "bg-yellow-100 text-yellow-800"
                : "bg-muted text-muted-foreground"
            }`}>
              {l.level}: {l.count}
            </span>
          ))}
        </div>
      )}
      {topErrors.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground font-medium">Top errors:</p>
          {topErrors.slice(0, 5).map((e, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground shrink-0">×{e.count}</span>
              <code className="text-xs break-all">{e.payload.slice(0, 120)}</code>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
