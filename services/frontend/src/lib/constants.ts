export const POLL_INTERVAL_MS = 5000
export const DEBOUNCE_MS = 350
export const SESSION_STORAGE_KEY = "vst-auth"
export const DEFAULT_PAGE_SIZE = 20
export const CHAT_SCROLL_THRESHOLD = 100
export const TOKEN_BATCH_INTERVAL_MS = 16   // ~60fps via requestAnimationFrame
export const MAX_HISTORY_DISPLAY = 50
export const INCIDENT_SUGGEST_ERRORS = 50
export const SIDEBAR_WIDTH = 240

export const SEVERITY_COLORS: Record<string, string> = {
  critical: "destructive",
  high: "destructive",
  medium: "secondary",
  low: "outline",
}

export const STATUS_COLORS: Record<string, string> = {
  open: "destructive",
  investigating: "secondary",
  resolved: "outline",
  closed: "outline",
  acknowledged: "secondary",
  suppressed: "outline",
}

export const INTENT_LABELS: Record<string, string> = {
  HEALTH_CHECK: "Kiểm tra sức khỏe",
  ERROR_LOOKUP: "Tra cứu lỗi",
  METRIC_QUERY: "Metrics",
  ALERT_STATUS: "Trạng thái alert",
  ROOT_CAUSE: "Root cause",
  TREND_ANALYSIS: "Phân tích xu hướng",
  SERVER_QUERY: "Truy vấn server",
  INCIDENT_ANALYSIS: "Phân tích incident",
  HTTP_ANALYSIS: "Phân tích HTTP",
  PASTE_ALERT: "Alert paste",
  CAPACITY_PLANNING: "Kế hoạch công suất",
  LOG_ANOMALY: "Bất thường log",
  SECURITY_AUDIT: "Kiểm tra bảo mật",
  ALERT_MANAGEMENT: "Quản lý alert",
  VERIFY_FIX: "Xác nhận fix",
  CLARIFICATION: "Làm rõ",
  THREAT_MODEL: "Mô hình đe dọa",
}
