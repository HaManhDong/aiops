"use client"
import { useState } from "react"
import { Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { PendingForm } from "@/types/api"

interface Props {
  form: PendingForm
  onSubmit: (text: string) => void
}

type Row = Record<string, string>

export function RequiresInputForm({ form, onSubmit }: Props) {
  const [rows, setRows] = useState<Row[]>([{}])

  function updateRow(idx: number, field: string, val: string) {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, [field]: val } : r)))
  }
  function addRow() { setRows((prev) => [...prev, {}]) }
  function removeRow(idx: number) { setRows((prev) => prev.filter((_, i) => i !== idx)) }

  function handleSubmit() {
    const servers = rows.filter((r) => Object.values(r).some((v) => v?.trim()))
    if (!servers.length) return
    const text = `/add-servers ${JSON.stringify(servers)}`
    onSubmit(text)
  }

  return (
    <div className="rounded-md border p-4 space-y-3 mt-2">
      <p className="text-sm font-medium">{form.message}</p>
      <div className="space-y-2">
        {rows.map((row, idx) => (
          <div key={idx} className="flex gap-2 items-end">
            {form.form.fields.map((f) => (
              <div key={f.name} className="flex-1 space-y-1">
                {idx === 0 && <Label className="text-xs">{f.label}{f.required && " *"}</Label>}
                <Input
                  value={row[f.name] ?? ""}
                  onChange={(e) => updateRow(idx, f.name, e.target.value)}
                  placeholder={f.label}
                  className="h-8 text-sm"
                />
              </div>
            ))}
            {form.form.allow_multiple && rows.length > 1 && (
              <Button size="icon" variant="ghost" className="h-8 w-8 shrink-0" onClick={() => removeRow(idx)}>
                <Trash2 className="h-3 w-3" />
              </Button>
            )}
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        {form.form.allow_multiple && (
          <Button size="sm" variant="outline" onClick={addRow}>
            <Plus className="h-4 w-4 mr-1" /> Thêm server
          </Button>
        )}
        <Button size="sm" onClick={handleSubmit}>Xác nhận</Button>
        <Button size="sm" variant="ghost" onClick={() => onSubmit("/skip")}>Bỏ qua</Button>
      </div>
    </div>
  )
}
