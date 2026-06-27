"use client"
import { useEffect, useRef, useCallback, useState } from "react"
import { usePathname } from "next/navigation"
import { toast } from "sonner"
import { v4 as uuidv4 } from "uuid"
import { useAuthStore } from "@/store/auth"
import { useChatStore } from "@/store/chat"
import { apiFetch } from "@/lib/api"
import { readSSEStream } from "@/lib/sse"
import { MessageBubble } from "./MessageBubble"
import { ChatInput } from "./ChatInput"
import { RequiresInputForm } from "./RequiresInputForm"
import type { ServerRow, LogStats, IncidentDraft, EsQuery } from "@/types/api"

interface Props {
  initialSessionId?: string
  initialAppId?: string
}

export function ChatWindow({ initialSessionId, initialAppId = "" }: Props) {
  const pathname = usePathname()
  const user = useAuthStore((s) => s.user)
  const setSessionId = useAuthStore((s) => s.setSessionId)

  const {
    messages, addMessage, appendToMessage, appendStepToMessage,
    appendEsQueryToMessage, setMessageServerTable, setMessageLogStats,
    setMessageIncidentDraft, setMessageError,
    convState, setConvState, pendingForm, setPendingForm,
    isStreaming, setIsStreaming, setCurrentAppId, setMessages, clearMessages,
  } = useChatStore()

  const [input, setInput] = useState("")
  const [appId, setAppId] = useState(initialAppId)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Load history if initialSessionId
  useEffect(() => {
    if (!initialSessionId) { clearMessages(); return }
    async function loadHistory() {
      try {
        const res = await apiFetch(`/api/v1/chat/history?session_id=${initialSessionId}&limit=50`)
        if (!res.ok) return
        const data = await res.json()
        const msgs = (data.messages ?? []).map((m: Record<string, unknown>) => ({
          id: uuidv4(),
          role: m.role as "user" | "assistant",
          content: m.content as string,
          created_at: m.timestamp as string,
          intent: (m.assistant_metadata as Record<string, unknown>)?.intent as string | undefined,
          sources_used: (m.assistant_metadata as Record<string, unknown>)?.sources_used as string[] | undefined,
          latency_ms: (m.assistant_metadata as Record<string, unknown>)?.latency_ms as number | undefined,
          server_table: (m.assistant_metadata as Record<string, unknown>)?.server_table as ServerRow[] | undefined,
          log_stats: (m.assistant_metadata as Record<string, unknown>)?.log_stats as LogStats | undefined,
          incident_draft: (m.assistant_metadata as Record<string, unknown>)?.incident_draft as IncidentDraft | undefined,
        }))
        setMessages(msgs)
        if (data.app_id) { setAppId(data.app_id); setCurrentAppId(data.app_id) }
      } catch { /* ignore */ }
    }
    loadHistory()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSessionId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || isStreaming) return

    const userMsgId = uuidv4()
    addMessage({ id: userMsgId, role: "user", content: text, created_at: new Date().toISOString() })
    const asstMsgId = uuidv4()
    addMessage({ id: asstMsgId, role: "assistant", content: "", created_at: new Date().toISOString() })
    setInput("")
    setIsStreaming(true)

    let tokenBuffer = ""
    let rafId: number | null = null

    function flushTokens() {
      if (tokenBuffer) { appendToMessage(asstMsgId, tokenBuffer); tokenBuffer = "" }
      rafId = null
    }

    try {
      const effectiveAppId = appId || (user?.allowed_apps[0] !== "all" ? user?.allowed_apps[0] ?? "" : "")
      const body: Record<string, string> = { message: text }
      if (effectiveAppId) body.app_id = effectiveAppId
      if (initialSessionId) body.session_id = initialSessionId

      const res = await apiFetch("/api/v1/chat", {
        method: "POST",
        body: JSON.stringify(body),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err?.detail ?? err?.title ?? `HTTP ${res.status}`)
      }

      for await (const { event, data } of readSSEStream(res)) {
        const d = data as Record<string, unknown>
        switch (event) {
          case "token":
            tokenBuffer += (d.token as string) ?? ""
            if (rafId === null) rafId = requestAnimationFrame(flushTokens)
            break
          case "step":
            appendStepToMessage(asstMsgId, (d.text as string) ?? "")
            break
          case "es_query":
            appendEsQueryToMessage(asstMsgId, d as unknown as EsQuery)
            break
          case "server_table":
            setMessageServerTable(asstMsgId, (d.servers as ServerRow[]) ?? [])
            break
          case "log_stats":
            setMessageLogStats(asstMsgId, d as unknown as LogStats)
            break
          case "incident_draft":
            setMessageIncidentDraft(asstMsgId, d as unknown as IncidentDraft)
            break
          case "requires_input":
            setPendingForm(d as unknown as import("@/types/api").PendingForm)
            setConvState("WAITING_SERVER_INPUT")
            break
          case "done": {
            if (rafId !== null) { cancelAnimationFrame(rafId); flushTokens() }
            const sid = d.session_id as string | undefined
            if (sid) {
              setSessionId(sid)
              if (pathname === "/chat") {
                window.history.replaceState(null, "", `/chat/${sid}`)
              }
            }
            if ((d.next_state as string) === "CONFIRMING_SERVER") {
              setConvState("CONFIRMING_SERVER")
            } else {
              setConvState("NORMAL")
            }
            const intentVal = d.intent as string | undefined
            const sources = d.sources_used as string[] | undefined
            const latency = d.latency_ms as number | undefined
            useChatStore.setState((s) => ({
              messages: s.messages.map((m) =>
                m.id === asstMsgId ? { ...m, intent: intentVal, sources_used: sources, latency_ms: latency } : m
              ),
            }))
            break
          }
          case "error": {
            if (rafId !== null) { cancelAnimationFrame(rafId); flushTokens() }
            const errMsg = (d.message as string) ?? "Lỗi không xác định"
            setMessageError(asstMsgId, errMsg)
            toast.error(errMsg)
            break
          }
        }
      }
    } catch (err: unknown) {
      if (rafId !== null) { cancelAnimationFrame(rafId); flushTokens() }
      const msg = err instanceof Error ? err.message : "Lỗi kết nối"
      setMessageError(asstMsgId, msg)
      toast.error(msg)
    } finally {
      setIsStreaming(false)
    }
  }, [
    isStreaming, appId, user, initialSessionId, pathname,
    addMessage, appendToMessage, appendStepToMessage, appendEsQueryToMessage,
    setMessageServerTable, setMessageLogStats, setMessageIncidentDraft,
    setMessageError, setPendingForm, setConvState, setIsStreaming, setSessionId,
  ])

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
            Đặt câu hỏi về hệ thống...
          </div>
        )}
        {messages.map((m, i) => (
          <MessageBubble
            key={m.id}
            message={m}
            isStreaming={isStreaming && i === messages.length - 1 && m.role === "assistant"}
          />
        ))}
        <div ref={bottomRef} />
      </div>

      {convState === "WAITING_SERVER_INPUT" && pendingForm && (
        <div className="px-4 pb-2">
          <RequiresInputForm form={pendingForm} onSubmit={(t) => { setPendingForm(null); sendMessage(t) }} />
        </div>
      )}

      {convState === "CONFIRMING_SERVER" && (
        <div className="flex gap-2 px-4 pb-2">
          <button className="text-sm text-primary underline" onClick={() => sendMessage("có")}>✓ Xác nhận lưu server</button>
          <button className="text-sm text-muted-foreground underline" onClick={() => { setConvState("NORMAL"); sendMessage("không") }}>✗ Hủy</button>
        </div>
      )}

      {convState === "NORMAL" && (
        <ChatInput
          value={input}
          onChange={setInput}
          onSubmit={() => sendMessage(input)}
          disabled={isStreaming}
        />
      )}
    </div>
  )
}
