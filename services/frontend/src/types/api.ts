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
  id: string
  app_id: string
  ip: string
  hostname: string
  os: string | null
  description: string | null
  role: string | null
  is_active: boolean
  added_by: string | null
  created_at: string | null
}

export interface DatasourceConfig {
  id: string
  app_id: string
  display_name: string
  elasticsearch_url: string
  elasticsearch_api_key: string | null
  app_log_index: string
  syslog_index: string
  prometheus_url: string | null
  kibana_url: string | null
  kibana_api_key: string | null
  alert_thresholds: Record<string, number>
  txt_watch_dirs: string[] | null
  log_provider: string
  metrics_provider: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ConnectionTestResult {
  ok: boolean
  latency_ms: number | null
  error: string | null
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

export interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  created_at: string
  server_table?: ServerRow[] | null
  log_stats?: LogStats | null
  incident_draft?: IncidentDraft | null
  es_queries?: EsQuery[] | null
  steps?: string[]
  intent?: string
  sources_used?: string[]
  latency_ms?: number
  error?: string
}

export interface ServerRow {
  hostname: string
  ip: string
  cpu_pct: number | null
  ram_pct: number | null
  disk_pct: number | null
  error_count?: number | null
  net_in_kbps?: number | null
  net_out_kbps?: number | null
  disk_read_kbps?: number | null
  disk_write_kbps?: number | null
}

export interface LogStats {
  by_level: { level: string; count: number }[]
  top_errors: { payload: string; count: number }[]
  kibana_link?: string | null
}

export interface IncidentDraft {
  title: string
  app_id: string
  incident_time: string
  severity: string
  description: string
}

export interface EsQuery {
  source: string
  type?: string
  index: string
  es_url: string
  body: Record<string, unknown>
}

export interface IncidentRead {
  id: string
  app_id: string
  title: string
  severity: string
  status: string
  description: string | null
  root_cause: string | null
  solution: string | null
  related_logs: unknown[] | null
  error_patterns: unknown[] | null
  affected_servers: unknown[] | null
  source: string
  chat_session_id: string | null
  created_by: string | null
  assigned_to: string | null
  resolved_by: string | null
  solution_at: string | null
  incident_time: string | null
  resolved_at: string | null
  created_at: string
  updated_at: string
}

export interface PredictionAlert {
  id: string
  app_id: string
  server_ip: string | null
  alert_type: string
  signal_group: string
  severity: string
  status: string
  title: string
  explanation: string | null
  metric_name: string | null
  current_value: number | null
  baseline_value: number | null
  predicted_at: string | null
  confidence: number | null
  evidence: Record<string, unknown> | null
  blast_radius: Record<string, unknown> | null
  is_true_positive: boolean | null
  resolved_at: string | null
  suppressed_until: string | null
  created_at: string
  updated_at: string
}

export interface NotificationConfig {
  id: string
  name: string
  app_id: string | null
  channel: "email" | "telegram"
  schedule_cron: string
  is_enabled: boolean
  recipients: string[]
  report_window_hours: number
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface AuditLog {
  id: string
  user_id: string | null
  action: string
  entity_type: string
  entity_id: string | null
  old_value: unknown | null
  new_value: unknown | null
  ip_address: string | null
  created_at: string
}

export interface TopologyNode {
  id: string
  version_id: string
  app_id: string
  node_key: string
  label: string
  node_type: string
  ip: string | null
  hostname: string | null
  health_status: string
  position_x: number
  position_y: number
  metadata: Record<string, unknown> | null
}

export interface TopologyEdge {
  id: string
  version_id: string
  app_id: string
  source_node_id: string
  target_node_id: string
  relation_type: string
  propagation_prob: number
  weight: number
  label: string | null
}

export interface ChatSession {
  id: string
  user_id: string
  app_id: string | null
  title: string | null
  label: string | null
  state: string
  created_at: string
  updated_at: string
}
