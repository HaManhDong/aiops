"use client"
import { create } from "zustand"
import type { ChatMessage, PendingForm, ServerRow, LogStats, IncidentDraft, EsQuery } from "@/types/api"

interface ChatStore {
  messages: ChatMessage[]
  convState: "NORMAL" | "WAITING_SERVER_INPUT" | "CONFIRMING_SERVER"
  pendingForm: PendingForm | null
  isStreaming: boolean
  currentAppId: string

  setMessages: (msgs: ChatMessage[]) => void
  addMessage: (msg: ChatMessage) => void
  appendToMessage: (id: string, token: string) => void
  appendStepToMessage: (id: string, text: string) => void
  appendEsQueryToMessage: (id: string, q: EsQuery) => void
  setMessageServerTable: (id: string, servers: ServerRow[]) => void
  setMessageLogStats: (id: string, stats: LogStats) => void
  setMessageIncidentDraft: (id: string, draft: IncidentDraft) => void
  setMessageError: (id: string, error: string) => void
  setConvState: (s: "NORMAL" | "WAITING_SERVER_INPUT" | "CONFIRMING_SERVER") => void
  setPendingForm: (f: PendingForm | null) => void
  setIsStreaming: (v: boolean) => void
  setCurrentAppId: (id: string) => void
  clearMessages: () => void
}

export const useChatStore = create<ChatStore>((set) => ({
  messages: [],
  convState: "NORMAL",
  pendingForm: null,
  isStreaming: false,
  currentAppId: "",

  setMessages: (msgs) => set({ messages: msgs }),
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),

  appendToMessage: (id, token) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, content: m.content + token } : m
      ),
    })),

  appendStepToMessage: (id, text) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, steps: [...(m.steps ?? []), text] } : m
      ),
    })),

  appendEsQueryToMessage: (id, q) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, es_queries: [...(m.es_queries ?? []), q] } : m
      ),
    })),

  setMessageServerTable: (id, servers) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, server_table: servers } : m
      ),
    })),

  setMessageLogStats: (id, stats) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, log_stats: stats } : m
      ),
    })),

  setMessageIncidentDraft: (id, draft) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, incident_draft: draft } : m
      ),
    })),

  setMessageError: (id, error) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, error } : m
      ),
    })),

  setConvState: (convState) => set({ convState }),
  setPendingForm: (pendingForm) => set({ pendingForm }),
  setIsStreaming: (isStreaming) => set({ isStreaming }),
  setCurrentAppId: (currentAppId) => set({ currentAppId }),
  clearMessages: () => set({ messages: [], convState: "NORMAL", pendingForm: null, isStreaming: false }),
}))
