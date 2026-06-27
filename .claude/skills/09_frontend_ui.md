# Skill: Frontend UI (Next.js 15)

## Stack

| Package | Mục đích |
|---|---|
| `next@15` + Turbopack | App Router, Server Components, streaming |
| `shadcn/ui` | Component library (chat bubble, table, card, badge, dialog) |
| `tailwindcss` + `autoprefixer` | Styling — **cả hai phải được cài** |
| `zustand` | Client state (JWT token, session_id, user info) |
| `react-markdown` | Render LLM response có markdown |
| `lucide-react` | Icons |
| `sonner` | Toast notifications |

**Lưu ý cài đặt:**
```bash
npm install
npm install autoprefixer --save-dev   # bắt buộc — thiếu gây Turbopack crash khi build CSS
```

## Project layout

```
frontend/src/
├── app/
│   ├── (auth)/login/page.tsx         ← Login form
│   ├── (app)/
│   │   ├── layout.tsx                ← AuthGuard (redirect /login nếu chưa đăng nhập)
│   │   ├── chat/page.tsx             ← Chat interface
│   │   ├── servers/page.tsx          ← Server registry
│   │   └── admin/
│   │       ├── layout.tsx            ← Admin role guard
│   │       └── datasources/page.tsx  ← Datasource CRUD (admin only)
│   └── layout.tsx                    ← Root layout + Toaster
├── components/
│   ├── chat/                         ← ChatWindow, MessageBubble, ChatInput,
│   │                                    ServerInputForm, ServerConfirmCard, SourceBadges
│   ├── layout/Sidebar.tsx
│   └── ui/                           ← shadcn/ui components (badge, button, card, ...)
├── lib/
│   ├── api.ts                        ← apiFetch / apiJson wrappers
│   └── sse.ts                        ← SSE stream reader
├── store/
│   ├── auth.ts                       ← Zustand (token, user, sessionId)
│   └── chat.ts                       ← Zustand (messages, convState, pendingForm)
└── types/api.ts                      ← TypeScript types (mirror Pydantic schemas)
```

---

## TypeScript types (`types/api.ts`)

**QUAN TRỌNG**: tất cả `id` field đều là `string` (UUID) sau khi migrate, không phải `number`.

```typescript
export interface UserInfo {
  id: string
  username: string
  full_name: string | null
  role: "admin" | "engineer" | "manager"
  allowed_apps: string[]
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: UserInfo
}

export interface ServerRegistryItem {
  id: string        // ← string UUID, KHÔNG phải number
  app_id: string
  ip: string
  hostname: string
  os: string | null
  description: string | null
  is_active: boolean
  added_by: string | null
  created_at: string | null
}

export interface DatasourceConfig {
  app_id: string
  display_name: string
  elasticsearch_url: string
  log_index_pattern: string
  prometheus_url: string | null
  kibana_url: string | null
  alert_thresholds: Record<string, number>
  txt_watch_dirs: string[] | null
  is_active: boolean
}

export interface DatasourceUpdate {
  display_name?: string
  elasticsearch_url?: string
  elasticsearch_api_key?: string
  log_index_pattern?: string
  prometheus_url?: string
  kibana_url?: string
  kibana_api_key?: string
  txt_watch_dirs?: string[]
  is_active?: boolean
}

export interface ConnectionTestResult {
  ok: boolean
  latency_ms: number | null
  error: string | null
}

export interface DatasourceTestResponse {
  app_id: string
  results: Record<string, ConnectionTestResult>
}

export interface PendingForm {
  type: string
  app_id: string
  message: string
  form: {
    fields: { name: string; label: string; required: boolean }[]
    allow_multiple: boolean
  }
}
```

---

## API client (`lib/api.ts`)

```typescript
import { useAuthStore } from "@/store/auth"

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? ""

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const token = useAuthStore.getState().token
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  })
  if (res.status === 401) {
    useAuthStore.getState().clear()
    window.location.href = "/login"
    throw new Error("Unauthorized")
  }
  return res
}

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.title ?? body?.detail ?? "Lỗi không xác định")
  }
  return res.json() as Promise<T>
}
```

---

## Auth flow

### Environment variable

```env
# .env.local — trỏ trực tiếp vào API, không qua Nginx trong dev
NEXT_PUBLIC_API_URL=http://localhost:8000

# Production — qua Nginx
NEXT_PUBLIC_API_URL=http://localhost
```

### Login (`app/(auth)/login/page.tsx`)

```typescript
// POST /api/v1/auth/token  ← đúng path, prefix /api/v1 bắt buộc
const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1/auth/token`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ username, password }),
})
const data = await res.json()
useAuthStore.getState().setToken(data.access_token, data.user)
router.push("/chat")
```

### Zustand auth store

```typescript
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
      token: null, user: null, sessionId: null,
      setToken: (token, user) => set({ token, user }),
      setSessionId: (id) => set({ sessionId: id }),
      clear: () => set({ token: null, user: null, sessionId: null }),
    }),
    { name: "vst-auth" }
  )
)
```

---

## Chat interface

### SSE event types

```typescript
type SSEEvent =
  | { event: "token";          data: { token: string } }
  | { event: "done";           data: { session_id: string; intent: string; sources_used: string[]; latency_ms: number } }
  | { event: "requires_input"; data: PendingForm }
  | { event: "error";          data: { code: string; message: string } }
```

### SSE stream reader (`lib/sse.ts`)

```typescript
export async function* readSSEStream(response: Response): AsyncGenerator<any> {
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const parts = buffer.split("\n\n")
    buffer = parts.pop() ?? ""

    for (const part of parts) {
      const lines = part.split("\n")
      let event = "message", data = ""
      for (const line of lines) {
        if (line.startsWith("event: ")) event = line.slice(7)
        if (line.startsWith("data: "))  data  = line.slice(6)
      }
      if (data) yield { event, data: JSON.parse(data) }
    }
  }
}
```

**Lưu ý**: Không dùng `EventSource` browser API — nó không hỗ trợ custom header Authorization.

---

## API Endpoints — đúng path

| Action | Method | Path |
|---|---|---|
| Login | POST | `/api/v1/auth/token` |
| Chat SSE | POST | `/api/v1/chat` |
| Chat history | GET | `/api/v1/chat/history?session_id=...` |
| List servers | GET | `/api/v1/servers?app_id=erp` |
| Add servers | POST | `/api/v1/servers` |
| Delete server | DELETE | `/api/v1/servers/{id}` — id là UUID string |
| List datasources | GET | `/api/v1/admin/datasources` |
| Update datasource | PUT | `/api/v1/admin/datasources/{app_id}` |
| Test datasource | GET | `/api/v1/admin/datasources/{app_id}/test` |

---

## Component specs

### `MessageBubble.tsx`
- User: căn phải, nền xanh nhạt
- Assistant: căn trái, render markdown, cursor nhấp nháy khi đang stream
- Footer sau `done`: `SourceBadges` + latency ms

### `ServerInputForm.tsx` — khi `convState === "WAITING_SERVER_INPUT"`
- Form nhập IP + hostname (có thể add nhiều row)
- Submit → gửi text thông thường qua POST /api/v1/chat
- Backend dùng LLM extract JSON → chuyển sang CONFIRMING_SERVER

### `ServerConfirmCard.tsx` — khi `convState === "CONFIRMING_SERVER"`
- Hiển thị server list đã parse
- "Xác nhận" → gửi "có", "Hủy" → gửi "không"

---

## Admin — Datasource management

Chỉ hiển thị với role `admin`. Guard trong `admin/layout.tsx`:

```typescript
const { user } = useAuthStore()
useEffect(() => {
  if (user && user.role !== "admin") {
    toast.error("Bạn không có quyền truy cập trang này")
    router.replace("/chat")
  }
}, [user, router])
if (!user || user.role !== "admin") return null
```

---

---

## Pagination

### Nguyên tắc
- API dùng `limit` + `offset` (offset-based), không dùng cursor — đơn giản hơn cho admin list.
- Page index **0-based** ở client, convert sang offset khi gọi API: `offset = page × pageSize`.
- Mọi filter/search thay đổi → reset `page = 0` ngay, không chờ fetch xong.
- `pageSize` thay đổi cũng reset page về 0 (vì offset cũ không còn hợp lệ).

### State cần thiết

```typescript
const [page, setPage]         = useState(0)
const [pageSize, setPageSize] = useState(10)   // default hiển thị
const [total, setTotal]       = useState(0)    // tổng record từ API

// Reset page khi bất kỳ filter nào thay đổi
useEffect(() => { setPage(0) }, [...allFilters, pageSize])
```

### Fetch pattern

```typescript
const load = useCallback(async () => {
  const params = new URLSearchParams({
    limit:  String(pageSize),
    offset: String(page * pageSize),
  })
  // thêm filter params tùy context
  const data = await apiJson<{ items: T[]; total: number }>(`/api/v1/resource?${params}`)
  setItems(data.items)
  setTotal(data.total)
}, [page, pageSize, ...allFilters])

useEffect(() => { load() }, [load])
```

### PaginationBar component

Tạo một component tái sử dụng nhận props: `total`, `page`, `pageSize`, `onPageChange`, `onPageSizeChange`. Component tự ẩn khi `total === 0`. Đặt **dưới bảng**, cùng hàng với số dòng/trang và nút prev/next.

```tsx
<PaginationBar
  total={total}
  page={page}
  pageSize={pageSize}
  onPageChange={setPage}
  onPageSizeChange={(size) => { setPageSize(size); setPage(0) }}
/>
```

---

## Search với debounce

### Vấn đề
Nếu dùng một state và gọi API trực tiếp trong `onChange`, mỗi keystroke gây một request — lãng phí và gây nhấp nháy.

### Giải pháp — tách hai state

| State | Cập nhật khi | Mục đích |
|---|---|---|
| `inputValue` | Mỗi keystroke | Giữ input hiển thị đúng |
| `query` | Sau 300–400ms không gõ | Trigger fetch |

```typescript
const [inputValue, setInputValue] = useState("")
const [query, setQuery]           = useState("")
const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

function handleChange(value: string) {
  setInputValue(value)
  if (timer.current) clearTimeout(timer.current)
  timer.current = setTimeout(() => setQuery(value), 350)
}

function handleClear() {
  setInputValue("")
  setQuery("")
  if (timer.current) clearTimeout(timer.current)
}
```

Dùng `query` (không phải `inputValue`) trong dependency array của `useCallback` load và trong URL params.

### UX
- Icon kính lúp bên trái input.
- Nút **×** xuất hiện khi `inputValue` không rỗng — clear cả hai state và timer ngay lập tức.
- Placeholder mô tả rõ tìm theo trường nào (không chỉ "Tìm kiếm...").

---

## Confirm Popups

**Không dùng `window.confirm`** — block main thread, không accessible, không style được.  
Luôn dùng `<Dialog>` từ shadcn/ui (hoặc component tương đương).

### Ba tình huống và cách xử lý

#### 1. Xác nhận xoá / hành động destructive

Lưu item sắp xoá vào state (`target`). Dialog mở khi `target !== null`. Confirm → gọi API → xoá `target` → refresh list.

```
[Trash button] → setTarget(item)
                      ↓
              <Dialog open={!!target}>
                [Huỷ] → setTarget(null)
                [Xoá] → deleteApi(target.id) → setTarget(null) → reload()
              </Dialog>
```

Luôn disable cả hai nút khi đang xoá (`loading` state). Nút xoá dùng `variant="destructive"`.

#### 2. Xác nhận thay đổi field (dropdown/select)

Vấn đề: `onChange` của select fires ngay lập tức — nếu gọi API thẳng, user không kịp suy nghĩ.

Pattern **deferred confirmation**: `onChange` không gọi API, chỉ lưu ý định vào state `pending`.

```
[Select onChange] → setPending({ patch, label })
                         ↓
               <Dialog open={!!pending}>
                 <p>{pending.label}</p>    ← mô tả thay đổi bằng ngôn ngữ tự nhiên
                 [Huỷ] → setPending(null)  ← select tự revert vì value vẫn là giá trị cũ
                 [Xác nhận] → callApi(pending.patch) → setPending(null) → reload()
               </Dialog>
```

`pending` có dạng `{ patch: Record<string, unknown>; label: string }` — đủ để Dialog hiển thị mô tả và để hàm apply gọi API.

**Lưu ý:** Dialog confirm dạng này nên đặt **ngoài** Sheet/Dialog đang mở chính để tránh nested portal.

#### 3. Inline edit trong list/timeline

Dùng khi row có nút edit nhỏ, không cần mở Dialog riêng để edit.

- Action buttons (edit/delete) **ẩn mặc định**, hiện khi hover — dùng Tailwind `group` + `group-hover:opacity-100`.
- Edit mode: thay thế text bằng `<Textarea>` + nút ✓/✕ ngay tại chỗ.
- Ctrl+Enter để submit (ghi vào `onKeyDown`).
- Delete vẫn cần Dialog confirm (Pattern 1 ở trên).
- Chỉ render action buttons khi user có quyền (`canManage(item)`).

```
Trạng thái bình thường:   [text content]   [✏ ✗] ← opacity-0, hiện khi hover
Trạng thái edit:          [<Textarea>]     [✓] [✕]
```

---

## Accessibility — Radix Dialog/Sheet

`DialogTitle` / `SheetTitle` **phải luôn có trong DOM** khi overlay đang open — kể cả khi data chưa load xong. Không đặt Title bên trong block render có điều kiện.

```tsx
// ❌ Sai — Title biến mất khi detail === null
{detail && <SheetTitle>{detail.title}</SheetTitle>}

// ✅ Đúng — Title luôn render, dùng skeleton khi chưa có data
<SheetTitle>
  {detail
    ? detail.title
    : <span className="inline-block h-5 w-48 animate-pulse rounded bg-muted" />}
</SheetTitle>
```

---

## Rules

1. **Token không dùng cookie** — lưu localStorage qua zustand-persist
2. **Không fetch từ Server Component** — API call có auth header phải ở Client Component
3. **SSE dùng fetch + ReadableStream** — không dùng `EventSource`
4. **Không hardcode API_BASE** — luôn đọc từ `NEXT_PUBLIC_API_URL`
5. **id luôn là string** — mọi entity từ API đều dùng UUID string, không phải number
6. **Không dùng `window.confirm`** — dùng Dialog pattern tương ứng với tình huống
7. **Debounce search ~350ms** — tách `inputValue` (UI) và `query` (fetch trigger)
8. **Reset page về 0** khi bất kỳ filter, search, hoặc pageSize thay đổi
9. **Offset-based pagination** — `offset = page × pageSize`, page index 0-based ở client

---

## Responsive Design

```
Desktop (≥768px):                Mobile (<768px):
┌──────────┬────────────────┐    ┌────────────────┐
│ Sidebar  │  Main content  │    │  Main content  │
│  240px   │   flex-1       │    │  full width    │
└──────────┴────────────────┘    └────────────────┘
                                  [≡] hamburger → Sheet drawer
```

Ẩn cột ít quan trọng trên mobile:
```typescript
<TableHead className="hidden md:table-cell">Created at</TableHead>
<TableCell className="hidden md:table-cell">{row.created_at}</TableCell>
```

Touch targets: mọi button phải ≥44×44px. `size="icon"` của shadcn đạt chuẩn này.
