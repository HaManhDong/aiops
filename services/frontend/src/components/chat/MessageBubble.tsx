"use client"
import ReactMarkdown from "react-markdown"
import { Bot, CheckCircle2, Clock3, DatabaseZap, UserRound } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { ServerTable } from "./ServerTable"
import { LogStatsCard } from "./LogStatsCard"
import { IncidentDraftCard } from "./IncidentDraftCard"
import { INTENT_LABELS } from "@/lib/constants"
import type { ChatMessage } from "@/types/api"

interface Props { message: ChatMessage; isStreaming?: boolean }

export function MessageBubble({ message, isStreaming }: Props) {
  const isUser = message.role === "user"

  if (isUser) {
    return (
      <div className="flex justify-end gap-3">
        <div className="max-w-[78%] rounded-2xl rounded-tr-md bg-gradient-to-br from-orange-500 to-amber-500 px-4 py-3 text-sm leading-relaxed text-white shadow-lg shadow-orange-500/15">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
        <div className="mt-1 hidden h-8 w-8 shrink-0 place-items-center rounded-full bg-orange-100 text-orange-700 sm:grid">
          <UserRound className="h-4 w-4" />
        </div>
      </div>
    )
  }

  return (
    <div className="flex max-w-[95%] gap-3">
      <div className="mt-1 grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-slate-950 text-orange-300 shadow-lg shadow-slate-950/15">
        <Bot className="h-4 w-4" />
      </div>

      <div className="min-w-0 flex-1 space-y-3">
        <div className="overflow-hidden rounded-2xl rounded-tl-md border border-orange-100 bg-white shadow-xl shadow-slate-200/60">
          <div className="flex flex-wrap items-center gap-2 border-b border-orange-100 bg-gradient-to-r from-orange-50 via-white to-amber-50 px-4 py-3">
            <span className="inline-flex items-center gap-2 text-sm font-semibold text-slate-900">
              <span className="grid h-6 w-6 place-items-center rounded-lg bg-orange-500 text-[11px] font-bold text-white">AI</span>
              Ops Copilot
            </span>
            {message.intent && (
              <Badge variant="outline" className="border-orange-200 bg-white/80 text-[11px] text-orange-700">
                {INTENT_LABELS[message.intent] ?? message.intent}
              </Badge>
            )}
            {message.sources_used?.map((source) => (
              <Badge key={source} variant="secondary" className="gap-1 bg-slate-100 text-[11px] text-slate-600">
                <DatabaseZap className="h-3 w-3" />
                {source}
              </Badge>
            ))}
            {message.latency_ms != null && !isStreaming && (
              <span className="ml-auto inline-flex items-center gap-1 text-xs text-slate-500">
                <Clock3 className="h-3 w-3" />
                {(message.latency_ms / 1000).toFixed(1)}s
              </span>
            )}
          </div>

          {message.steps?.length ? (
            <div className="border-b border-slate-100 bg-slate-50/70 px-4 py-2">
              <div className="flex flex-wrap gap-2">
                {message.steps.map((step, index) => (
                  <span key={`${step}-${index}`} className="inline-flex items-center gap-1 rounded-full bg-white px-2.5 py-1 text-xs text-slate-500 ring-1 ring-slate-200">
                    <CheckCircle2 className="h-3 w-3 text-orange-500" />
                    {step}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          <div className="px-5 py-4">
            {message.content ? (
              <div className="prose prose-sm max-w-none text-slate-800 prose-p:my-2 prose-p:leading-7 prose-strong:text-slate-950 prose-ul:my-3 prose-li:my-1 prose-code:rounded prose-code:bg-orange-50 prose-code:px-1.5 prose-code:py-0.5 prose-code:text-orange-700 prose-code:before:content-none prose-code:after:content-none">
                <ReactMarkdown>{message.content}</ReactMarkdown>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="h-3 w-2/3 animate-pulse rounded bg-slate-100" />
                <div className="h-3 w-1/2 animate-pulse rounded bg-slate-100" />
              </div>
            )}
            {isStreaming && (
              <span className="mt-1 inline-block h-4 w-0.5 animate-pulse bg-orange-500" />
            )}
          </div>
        </div>

        {message.server_table && <ServerTable servers={message.server_table} />}
        {message.log_stats && <LogStatsCard stats={message.log_stats} intent={message.intent} />}
        {message.incident_draft && <IncidentDraftCard draft={message.incident_draft} />}

        {message.error && (
          <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{message.error}</p>
        )}
      </div>
    </div>
  )
}
