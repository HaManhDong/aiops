"use client"
import { create } from "zustand"
import { persist } from "zustand/middleware"
import type { UserInfo } from "@/types/api"

interface AuthState {
  token: string | null
  user: UserInfo | null
  sessionId: string | null
  setToken: (token: string, user: UserInfo) => void
  setSessionId: (id: string) => void
  clear: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      sessionId: null,
      setToken: (token, user) => set({ token, user }),
      setSessionId: (id) => set({ sessionId: id }),
      clear: () => set({ token: null, user: null, sessionId: null }),
    }),
    { name: "vst-auth" }
  )
)
