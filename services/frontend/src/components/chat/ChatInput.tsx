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
    <div className="flex gap-2 items-end p-3 border-t bg-background">
      <Textarea
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder ?? "Nhập câu hỏi... (Enter để gửi, Shift+Enter xuống dòng)"}
        rows={2}
        className="resize-none flex-1 min-h-[60px] max-h-[120px]"
        disabled={disabled}
      />
      <Button
        size="icon"
        className="h-10 w-10 shrink-0"
        disabled={disabled || !value.trim()}
        onClick={onSubmit}
      >
        <Send className="h-4 w-4" />
      </Button>
    </div>
  )
}
