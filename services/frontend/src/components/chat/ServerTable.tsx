"use client"
import type { ReactNode } from "react"
import { Cpu, HardDrive, MemoryStick, Server } from "lucide-react"
import type { ServerRow } from "@/types/api"

function fmt(v: number | null | undefined, suffix = "%") {
  if (v == null) return "N/A"
  return `${v.toFixed(1)}${suffix}`
}
function fmtKbps(v: number | null | undefined) {
  if (v == null) return "N/A"
  if (v >= 1024) return `${(v / 1024).toFixed(1)} MB/s`
  return `${v.toFixed(0)} KB/s`
}
function colorPct(v: number | null | undefined) {
  if (v == null) return ""
  if (v >= 90) return "text-red-700"
  if (v >= 75) return "text-amber-700"
  return "text-emerald-700"
}
function barColor(v: number | null | undefined) {
  if (v == null) return "bg-slate-200"
  if (v >= 90) return "bg-red-500"
  if (v >= 75) return "bg-amber-500"
  return "bg-emerald-500"
}

interface Props { servers: ServerRow[] }

export function ServerTable({ servers }: Props) {
  if (!servers?.length) return null
  const hasIo = servers.some(
    (s) => s.net_in_kbps != null || s.net_out_kbps != null || s.disk_read_kbps != null || s.disk_write_kbps != null
  )

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-lg shadow-slate-200/50">
      <div className="mb-3 flex items-center gap-2">
        <div className="grid h-8 w-8 place-items-center rounded-lg bg-orange-100 text-orange-700">
          <Server className="h-4 w-4" />
        </div>
        <div>
          <p className="text-sm font-semibold text-slate-900">Server Health</p>
          <p className="text-xs text-muted-foreground">{servers.length} node đang được theo dõi</p>
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        {servers.map((server, index) => (
          <div key={`${server.hostname}-${index}`} className="rounded-xl border border-slate-100 bg-slate-50/60 p-3">
            <div className="mb-3 flex items-start justify-between gap-3">
              <div>
                <p className="font-mono text-sm font-semibold text-slate-900">{server.hostname}</p>
                <p className="font-mono text-xs text-muted-foreground">{server.ip}</p>
              </div>
              <span className="rounded-full bg-white px-2 py-1 text-[11px] font-medium text-slate-500 ring-1 ring-slate-200">
                live
              </span>
            </div>
            <div className="space-y-2">
              <MetricBar icon={<Cpu className="h-3.5 w-3.5" />} label="CPU" value={server.cpu_pct} />
              <MetricBar icon={<MemoryStick className="h-3.5 w-3.5" />} label="RAM" value={server.ram_pct} />
              <MetricBar icon={<HardDrive className="h-3.5 w-3.5" />} label="Disk" value={server.disk_pct} />
            </div>
            {hasIo && (
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground md:grid-cols-4">
                <IoPill label="Net↓" value={fmtKbps(server.net_in_kbps)} />
                <IoPill label="Net↑" value={fmtKbps(server.net_out_kbps)} />
                <IoPill label="DiskR" value={fmtKbps(server.disk_read_kbps)} />
                <IoPill label="DiskW" value={fmtKbps(server.disk_write_kbps)} />
              </div>
            )}
          </div>
          ))}
      </div>
    </div>
  )
}

function MetricBar({
  icon,
  label,
  value,
}: {
  icon: ReactNode
  label: string
  value: number | null | undefined
}) {
  const width = value == null ? 0 : Math.max(0, Math.min(100, value))
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="inline-flex items-center gap-1.5 font-medium text-slate-600">{icon}{label}</span>
        <span className={`font-semibold ${colorPct(value)}`}>{fmt(value)}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-white">
        <div className={`h-full rounded-full ${barColor(value)}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  )
}

function IoPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-white px-2 py-1 ring-1 ring-slate-200">
      <span className="block text-[10px] uppercase tracking-wide text-slate-400">{label}</span>
      <span className="font-medium text-slate-700">{value}</span>
    </div>
  )
}
