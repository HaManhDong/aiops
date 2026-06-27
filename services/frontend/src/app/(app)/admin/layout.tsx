"use client"
import { useEffect } from "react"
import { useRouter } from "next/navigation"
import { toast } from "sonner"
import { useAuthStore } from "@/store/auth"

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)

  useEffect(() => {
    if (user && user.role !== "admin") {
      toast.error("Bạn không có quyền truy cập trang này")
      router.replace("/dashboard")
    }
  }, [user, router])

  if (!user || user.role !== "admin") return null
  return <>{children}</>
}
