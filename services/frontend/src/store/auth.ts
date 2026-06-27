"use client"
import { create } from "zustand"
import { persist } from "zustand/middleware"
import type { UserInfo } from "@/types/api"

interface AuthState {
  token: string | null
  user: UserInfo | null
  sessionId: string | null
  hasHydrated: boolean
  setToken: (token: string, user: UserInfo) => void
  setSessionId: (id: string) => void
  setHasHydrated: (value: boolean) => void
  clear: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      sessionId: null,
      hasHydrated: false,
      setToken: (token, user) => set({ token, user }),
      setSessionId: (id) => set({ sessionId: id }),
      setHasHydrated: (hasHydrated) => set({ hasHydrated }),
      clear: () => set({ token: null, user: null, sessionId: null }),
    }),
    {
      name: "vst-auth",
      partialize: (state) => ({
        token: state.token,
        user: state.user,
        sessionId: state.sessionId,
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true)
      },
    }
  )
)
