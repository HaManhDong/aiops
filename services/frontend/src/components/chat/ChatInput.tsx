"use client"
import { useRef } from "react"
import { Send } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

interface Props {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  disabled?: boolean
  placeholder?: string
}

export function ChatInput({ value, onChange, onSubmit, disabled, placeholder }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null)

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      if (!disabled && value.trim()) onSubmit()
    }
  }

  return (
    <div className="border-t border-orange-100 bg-white/90 p-4 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-end gap-3 rounded-2xl border border-orange-100 bg-white p-2 shadow-xl shadow-slate-200/60">
      <Textarea
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder ?? "Nhập câu hỏi... (Enter để gửi, Shift+Enter xuống dòng)"}
        rows={2}
        className="min-h-[56px] max-h-[140px] flex-1 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
        disabled={disabled}
      />
      <Button
        size="icon"
        className="h-11 w-11 shrink-0 rounded-xl bg-gradient-to-br from-orange-500 to-amber-500 text-white shadow-lg shadow-orange-500/20 hover:from-orange-600 hover:to-amber-600"
        disabled={disabled || !value.trim()}
        onClick={onSubmit}
      >
        <Send className="h-4 w-4" />
      </Button>
      </div>
    </div>
  )
}
