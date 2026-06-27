import { beforeEach, describe, expect, it } from "vitest"

import { useAuthStore } from "./auth"
import type { UserInfo } from "@/types/api"

const user: UserInfo = {
  id: "usr-admin-001",
  username: "admin",
  full_name: "System Admin",
  role: "admin",
  allowed_apps: ["all"],
}

describe("useAuthStore", () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: null,
      user: null,
      sessionId: null,
      hasHydrated: false,
    })
  })

  it("stores token and user after login", () => {
    useAuthStore.getState().setToken("jwt-token", user)

    expect(useAuthStore.getState().token).toBe("jwt-token")
    expect(useAuthStore.getState().user?.username).toBe("admin")
  })

  it("tracks hydration state separately from persisted auth data", () => {
    useAuthStore.getState().setHasHydrated(true)

    expect(useAuthStore.getState().hasHydrated).toBe(true)
  })

  it("clears auth data without changing hydration state", () => {
    useAuthStore.setState({ token: "jwt-token", user, sessionId: "sess_1", hasHydrated: true })

    useAuthStore.getState().clear()

    expect(useAuthStore.getState().token).toBeNull()
    expect(useAuthStore.getState().user).toBeNull()
    expect(useAuthStore.getState().sessionId).toBeNull()
    expect(useAuthStore.getState().hasHydrated).toBe(true)
  })
})
