"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"
import { useAuthStore } from "@/store/auth"

export default function HomePage() {
  const router = useRouter()
  const token = useAuthStore((state) => state.token)
  const hasHydrated = useAuthStore((state) => state.hasHydrated)

  useEffect(() => {
    if (!hasHydrated) return
    router.replace(token ? "/dashboard" : "/login")
  }, [hasHydrated, router, token])

  return (
    <div className="grid min-h-screen place-items-center bg-background text-sm text-muted-foreground">
      Đang chuyển hướng...
    </div>
  )
}
