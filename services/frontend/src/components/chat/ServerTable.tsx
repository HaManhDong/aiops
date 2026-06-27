"use client"
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
  if (v >= 90) return "text-destructive font-semibold"
  if (v >= 75) return "text-yellow-600 font-semibold"
  return ""
}

interface Props { servers: ServerRow[] }

export function ServerTable({ servers }: Props) {
  if (!servers?.length) return null
  const hasIo = servers.some(
    (s) => s.net_in_kbps != null || s.net_out_kbps != null || s.disk_read_kbps != null || s.disk_write_kbps != null
  )

  return (
    <div className="overflow-x-auto rounded-md border text-sm mt-2">
      <table className="w-full">
        <thead className="bg-muted/50">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Hostname</th>
            <th className="px-3 py-2 text-right font-medium">IP</th>
            <th className="px-3 py-2 text-right font-medium">CPU</th>
            <th className="px-3 py-2 text-right font-medium">RAM</th>
            <th className="px-3 py-2 text-right font-medium">Disk</th>
            {hasIo && (
              <>
                <th className="px-3 py-2 text-right font-medium hidden md:table-cell">Net↓</th>
                <th className="px-3 py-2 text-right font-medium hidden md:table-cell">Net↑</th>
                <th className="px-3 py-2 text-right font-medium hidden md:table-cell">DiskR</th>
                <th className="px-3 py-2 text-right font-medium hidden md:table-cell">DiskW</th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {servers.map((s, i) => (
            <tr key={i} className="border-t">
              <td className="px-3 py-2 font-mono text-xs">{s.hostname}</td>
              <td className="px-3 py-2 font-mono text-xs text-right text-muted-foreground">{s.ip}</td>
              <td className={`px-3 py-2 text-right ${colorPct(s.cpu_pct)}`}>{fmt(s.cpu_pct)}</td>
              <td className={`px-3 py-2 text-right ${colorPct(s.ram_pct)}`}>{fmt(s.ram_pct)}</td>
              <td className={`px-3 py-2 text-right ${colorPct(s.disk_pct)}`}>{fmt(s.disk_pct)}</td>
              {hasIo && (
                <>
                  <td className="px-3 py-2 text-right text-muted-foreground hidden md:table-cell">{fmtKbps(s.net_in_kbps)}</td>
                  <td className="px-3 py-2 text-right text-muted-foreground hidden md:table-cell">{fmtKbps(s.net_out_kbps)}</td>
                  <td className="px-3 py-2 text-right text-muted-foreground hidden md:table-cell">{fmtKbps(s.disk_read_kbps)}</td>
                  <td className="px-3 py-2 text-right text-muted-foreground hidden md:table-cell">{fmtKbps(s.disk_write_kbps)}</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
