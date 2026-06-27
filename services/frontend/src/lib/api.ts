import { useAuthStore } from "@/store/auth"

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? ""

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const token = useAuthStore.getState().token
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  })
  if (res.status === 401) {
    useAuthStore.getState().clear()
    if (typeof window !== "undefined") window.location.href = "/login"
    throw new Error("Unauthorized")
  }
  return res
}

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const msg = body?.title ?? body?.detail ?? `HTTP ${res.status}`
    throw new Error(msg)
  }
  return res.json() as Promise<T>
}
