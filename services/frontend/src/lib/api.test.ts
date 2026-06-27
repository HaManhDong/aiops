import { beforeEach, describe, expect, it, vi } from "vitest"

import { apiFetch, apiJson } from "./api"
import { useAuthStore } from "@/store/auth"
import type { UserInfo } from "@/types/api"

const user: UserInfo = {
  id: "usr-admin-001",
  username: "admin",
  full_name: "System Admin",
  role: "admin",
  allowed_apps: ["all"],
}

describe("api client", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useAuthStore.setState({ token: null, user: null, sessionId: null, hasHydrated: true })
  })

  it("adds bearer token when authenticated", async () => {
    useAuthStore.getState().setToken("jwt-token", user)
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    await apiFetch("/api/v1/chat/sessions")

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/chat/sessions",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer jwt-token",
          "Content-Type": "application/json",
        }),
      })
    )
  })

  it("clears auth state on 401", async () => {
    useAuthStore.getState().setToken("jwt-token", user)
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })))

    await expect(apiFetch("/api/v1/chat/sessions")).rejects.toThrow("Unauthorized")

    expect(useAuthStore.getState().token).toBeNull()
    expect(useAuthStore.getState().user).toBeNull()
  })

  it("apiJson returns parsed json on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [1, 2, 3] }), { status: 200 })
    ))

    await expect(apiJson<{ items: number[] }>("/api/v1/demo")).resolves.toEqual({ items: [1, 2, 3] })
  })

  it("apiJson surfaces backend error title", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ title: "Datasource không tồn tại" }), { status: 404 })
    ))

    await expect(apiJson("/api/v1/missing")).rejects.toThrow("Datasource không tồn tại")
  })
})
