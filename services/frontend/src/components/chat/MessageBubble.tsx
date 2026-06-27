"use client"
import ReactMarkdown from "react-markdown"
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
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-primary text-primary-foreground px-4 py-2 text-sm">
          {message.content}
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1 max-w-[90%]">
      {/* Steps */}
      {message.steps?.map((s, i) => (
        <p key={i} className="text-xs text-muted-foreground italic">{s}</p>
      ))}

      {/* Main content */}
      <div className="rounded-2xl rounded-tl-sm bg-muted px-4 py-2 text-sm prose prose-sm dark:prose-invert max-w-none">
        <ReactMarkdown>{message.content}</ReactMarkdown>
        {isStreaming && (
          <span className="inline-block h-4 w-0.5 bg-primary animate-pulse ml-0.5" />
        )}
      </div>

      {/* Server table */}
      {message.server_table && <ServerTable servers={message.server_table} />}

      {/* Log stats */}
      {message.log_stats && <LogStatsCard stats={message.log_stats} intent={message.intent} />}

      {/* Incident draft */}
      {message.incident_draft && <IncidentDraftCard draft={message.incident_draft} />}

      {/* Footer */}
      {message.intent && !isStreaming && (
        <div className="flex flex-wrap gap-1 mt-1">
          <Badge variant="outline" className="text-xs">
            {INTENT_LABELS[message.intent] ?? message.intent}
          </Badge>
          {message.sources_used?.map((s) => (
            <Badge key={s} variant="secondary" className="text-xs">{s}</Badge>
          ))}
          {message.latency_ms != null && (
            <span className="text-xs text-muted-foreground ml-1">{(message.latency_ms / 1000).toFixed(1)}s</span>
          )}
        </div>
      )}

      {/* Error */}
      {message.error && (
        <p className="text-xs text-destructive">{message.error}</p>
      )}
    </div>
  )
}
