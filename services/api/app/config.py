from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ─── MariaDB ─────────────────────────────────────────────────────
    mariadb_host: str = "localhost"
    mariadb_port: int = 3306
    mariadb_db: str = "vst_ai"
    mariadb_user: str = "vst_ai_user"
    mariadb_password: str = "changeme"
    mariadb_replica_host: str = ""

    # ─── Redis ───────────────────────────────────────────────────────
    redis_sentinel_hosts: str = "redis-sentinel-1:26379"
    redis_sentinel_master: str = "mymaster"
    redis_password: str = ""
    redis_standalone_url: str = ""  # set → standalone mode (dev)

    # ─── JWT ─────────────────────────────────────────────────────────
    jwt_secret: str = "changeme_min_32_chars_abcdefghijklmnopqrst"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 8

    # ─── Encryption ──────────────────────────────────────────────────
    encryption_key: str = "0" * 64

    # ─── LLM ─────────────────────────────────────────────────────────
    llm_provider: str = "openai_compatible"
    llm_url: str = "http://ollama:11434"
    llm_model: str = "qwen2.5:14b"
    llm_api_key: str = ""

    # ─── Timeouts (seconds) ──────────────────────────────────────────
    es_logs_timeout: float = 15.0
    llm_json_timeout: float = 90.0
    llm_stream_timeout: float = 120.0

    # ─── ES query ────────────────────────────────────────────────────
    es_logs_size_normal: int = 10
    es_agg_topk: int = 10
    es_result_cache_ttl: int = 60       # Redis TTL cho ES query cache (seconds)

    # ─── Chat pipeline ───────────────────────────────────────────────
    dedup_jaccard_threshold: float = 0.72
    llm_max_context_chars: int = 12000
    llm_max_history_turns: int = 5
    llm_max_history_content_chars: int = 400
    conv_state_cache_ttl: int = 1800    # 30 phút
    incident_window_minutes_default: int = 60
    chat_session_title_length: int = 50

    # ─── Metrics thresholds (system-wide defaults) ───────────────────
    metric_cpu_warn: float = 75.0
    metric_cpu_crit: float = 90.0
    metric_ram_warn: float = 80.0
    metric_ram_crit: float = 95.0
    metric_disk_warn: float = 80.0
    metric_disk_crit: float = 90.0

    # ─── Prometheus timeouts ──────────────────────────────────────────
    prometheus_query_timeout: float = 5.0
    prometheus_range_timeout: float = 15.0

    # ─── ExpertAgent ──────────────────────────────────────────────────
    expert_max_iterations: int = 4
    expert_evidence_min_confidence: float = 0.6

    # ─── Kibana ───────────────────────────────────────────────────────
    kibana_timeout: float = 10.0
    kibana_alert_cache_ttl: int = 60

    # ─── Service probe ────────────────────────────────────────────────
    service_probe_timeout: float = 5.0

    # ─── Worker ───────────────────────────────────────────────────────
    worker_batch_size: int = 100
    worker_es_index_prefix: str = "vst-txt-logs"

    # ─── App ─────────────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    @property
    def database_url(self) -> str:
        return (
            f"mysql+asyncmy://{self.mariadb_user}:{self.mariadb_password}"
            f"@{self.mariadb_host}:{self.mariadb_port}/{self.mariadb_db}"
            f"?charset=utf8mb4"
        )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def _validate_secrets(self) -> None:
        if self.app_env != "production":
            return
        if len(self.jwt_secret) < 32 or self.jwt_secret.startswith("changeme"):
            raise ValueError("JWT_SECRET không hợp lệ cho production (min 32 chars, không dùng placeholder)")
        if self.encryption_key == "0" * 64:
            raise ValueError("ENCRYPTION_KEY chưa được cấu hình cho production")

    model_config = {"env_file": ".env", "case_sensitive": False}


settings = Settings()
