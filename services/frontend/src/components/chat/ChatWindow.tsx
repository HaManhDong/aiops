"use client"
import { useEffect, useRef, useCallback, useState } from "react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { toast } from "sonner"
import { v4 as uuidv4 } from "uuid"
import { useAuthStore } from "@/store/auth"
import { useChatStore } from "@/store/chat"
import { apiFetch, apiJson } from "@/lib/api"
import { readSSEStream } from "@/lib/sse"
import { MessageBubble } from "./MessageBubble"
import { ChatInput } from "./ChatInput"
import { RequiresInputForm } from "./RequiresInputForm"
import type { ChatSession, ServerRow, LogStats, IncidentDraft, EsQuery } from "@/types/api"

interface Props {
  initialSessionId?: string
  initialAppId?: string
}

export function ChatWindow({ initialSessionId, initialAppId = "" }: Props) {
  const pathname = usePathname()
  const router = useRouter()
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
  const [currentSessionId, setCurrentSessionId] = useState(initialSessionId ?? "")
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  const loadSessions = useCallback(async () => {
    try {
      const data = await apiJson<ChatSession[]>("/api/v1/chat/sessions?limit=50")
      setSessions(Array.isArray(data) ? data : [])
    } catch {
      setSessions([])
    }
  }, [])

  useEffect(() => { loadSessions() }, [loadSessions])

  useEffect(() => {
    setCurrentSessionId(initialSessionId ?? "")
  }, [initialSessionId])

  // Load history if currentSessionId
  useEffect(() => {
    if (!currentSessionId) {
      clearMessages()
      setAppId(initialAppId)
      setCurrentAppId(initialAppId)
      return
    }
    async function loadHistory() {
      setHistoryLoading(true)
      try {
        const res = await apiFetch(`/api/v1/chat/history?session_id=${currentSessionId}&limit=100`)
        if (!res.ok) return
        const data = await res.json() as Record<string, unknown>[]
        const msgs = data.map((m) => {
          const metadata = (m.assistant_metadata as Record<string, unknown> | null) ?? {}
          return {
          id: (m.id as string) || uuidv4(),
          role: m.role as "user" | "assistant",
          content: m.content as string,
          created_at: m.created_at as string,
          intent: metadata.intent as string | undefined,
          sources_used: metadata.sources_used as string[] | undefined,
          latency_ms: metadata.latency_ms as number | undefined,
          server_table: metadata.server_table as ServerRow[] | undefined,
          log_stats: metadata.log_stats as LogStats | undefined,
          incident_draft: metadata.incident_draft as IncidentDraft | undefined,
        }})
        setMessages(msgs)
        const session = sessions.find((item) => item.id === currentSessionId)
        if (session?.app_id) { setAppId(session.app_id); setCurrentAppId(session.app_id) }
      } catch {
        toast.error("Không tải được lịch sử chat")
      } finally {
        setHistoryLoading(false)
      }
    }
    loadHistory()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentSessionId])

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
      if (currentSessionId) body.session_id = currentSessionId

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
              setCurrentSessionId(sid)
              setSessionId(sid)
              if (pathname === "/chat") {
                window.history.replaceState(null, "", `/chat/${sid}`)
              }
              loadSessions()
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
    isStreaming, appId, user, currentSessionId, pathname, loadSessions,
    addMessage, appendToMessage, appendStepToMessage, appendEsQueryToMessage,
    setMessageServerTable, setMessageLogStats, setMessageIncidentDraft,
    setMessageError, setPendingForm, setConvState, setIsStreaming, setSessionId,
  ])

  async function handleDeleteSession(sessionId: string) {
    try {
      await apiFetch(`/api/v1/chat/sessions/${sessionId}`, { method: "DELETE" })
      toast.success("Đã xóa lịch sử chat")
      await loadSessions()
      if (sessionId === currentSessionId) {
        setCurrentSessionId("")
        clearMessages()
        router.replace("/chat")
      }
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Không xóa được lịch sử")
    }
  }

  return (
    <div className="flex h-[calc(100vh-0px)] min-h-0 overflow-hidden bg-[radial-gradient(circle_at_top_left,rgba(251,146,60,0.12),transparent_32%),linear-gradient(180deg,#fff7ed_0%,#ffffff_36%)]">
      <aside className="sticky top-0 hidden h-screen w-72 shrink-0 border-r border-orange-100 bg-white/80 p-3 shadow-xl shadow-slate-200/40 backdrop-blur md:flex md:flex-col">
        <div className="mb-3 flex items-center justify-between gap-2">
          <p className="text-sm font-semibold">Lịch sử chat</p>
          <Link
            href="/chat"
            onClick={() => {
              setCurrentSessionId("")
              clearMessages()
            }}
            className="rounded-md border px-2 py-1 text-xs hover:bg-muted"
          >
            Chat mới
          </Link>
        </div>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
          {sessions.length === 0 && (
            <p className="px-2 py-6 text-center text-xs text-muted-foreground">Chưa có lịch sử.</p>
          )}
          {sessions.map((session) => (
            <div
              key={session.id}
              className={`group flex items-start gap-2 rounded-lg px-2 py-2 text-sm ${
                session.id === currentSessionId ? "bg-orange-50 text-orange-950 ring-1 ring-orange-200" : "hover:bg-slate-50"
              }`}
            >
              <Link href={`/chat/${session.id}`} className="min-w-0 flex-1">
                <span className="block truncate font-medium">{session.title || "Cuộc chat chưa đặt tên"}</span>
                <span className="block truncate text-xs text-muted-foreground">
                  {session.app_id || "general"} · {new Date(session.updated_at).toLocaleString("vi")}
                </span>
              </Link>
              <button
                className="text-xs text-muted-foreground opacity-0 hover:text-destructive group-hover:opacity-100"
                onClick={() => handleDeleteSession(session.id)}
                aria-label="Xóa lịch sử chat"
              >
                Xóa
              </button>
            </div>
          ))}
        </div>
      </aside>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
        {historyLoading && (
          <p className="text-center text-xs text-muted-foreground">Đang tải lịch sử...</p>
        )}
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
    </div>
  )
}
