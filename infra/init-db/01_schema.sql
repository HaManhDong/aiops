CREATE DATABASE IF NOT EXISTS vst_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE vst_ai;

-- ─── users ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id            VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    username      VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name     VARCHAR(200),
    role          ENUM('admin','engineer','manager') NOT NULL DEFAULT 'engineer',
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

-- ─── user_app_permissions ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_app_permissions (
    id         VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    user_id    VARCHAR(36)  NOT NULL,
    app_id     VARCHAR(50)  NOT NULL,
    created_at DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_user_app (user_id, app_id),
    CONSTRAINT fk_uap_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ─── datasource_configs ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS datasource_configs (
    id                    VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    app_id                VARCHAR(50)  NOT NULL UNIQUE,
    display_name          VARCHAR(200) NOT NULL,
    elasticsearch_url     TEXT         NOT NULL,
    elasticsearch_api_key TEXT,
    app_log_index         VARCHAR(500) NOT NULL,
    syslog_index          VARCHAR(200) NOT NULL DEFAULT 'vst-txt-logs',
    prometheus_url        TEXT,
    prometheus_extra_labels JSON,
    kibana_url            TEXT,
    kibana_api_key        TEXT,
    alert_thresholds      JSON NOT NULL DEFAULT ('{"cpu_pct":85,"ram_pct":90,"disk_pct":85,"error_count_1h":10,"error_count_critical_1h":3,"connection_timeout_1h":10,"oracle_deadlock_1h":3,"smtp_error_30m":5}'),
    txt_watch_dirs        JSON,
    log_provider          VARCHAR(50) NOT NULL DEFAULT 'elasticsearch',
    metrics_provider      VARCHAR(50) NOT NULL DEFAULT 'prometheus',
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at            DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

-- ─── servers ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS servers (
    id               VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    app_id           VARCHAR(50)  NOT NULL,
    ip               VARCHAR(45)  NOT NULL,
    hostname         VARCHAR(255) NOT NULL,
    os               VARCHAR(100),
    description      TEXT,
    role             VARCHAR(100),
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    added_by         VARCHAR(36),
    created_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_app_ip (app_id, ip),
    INDEX idx_app_active (app_id, is_active),
    CONSTRAINT fk_sr_user FOREIGN KEY (added_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ─── system_settings ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS system_settings (
    id          VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    key_name    VARCHAR(100) NOT NULL UNIQUE,
    value       TEXT,
    created_at  DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at  DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

-- ─── audit_logs ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_logs (
    id          VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    user_id     VARCHAR(36),
    action      VARCHAR(100) NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    entity_id   VARCHAR(200),
    old_value   JSON,
    new_value   JSON,
    ip_address  VARCHAR(45),
    created_at  DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_created (created_at),
    INDEX idx_user (user_id),
    CONSTRAINT fk_al_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ─── error_classifier_patterns ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS error_classifier_patterns (
    id          VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    app_id      VARCHAR(50),
    pattern     VARCHAR(500) NOT NULL,
    error_type  VARCHAR(100) NOT NULL,
    severity    ENUM('critical','error','warning') NOT NULL DEFAULT 'error',
    priority    INT NOT NULL DEFAULT 100,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

-- ─── chat_sessions ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chat_sessions (
    id           VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    user_id      VARCHAR(36)  NOT NULL,
    app_id       VARCHAR(50),
    title        VARCHAR(100),
    label        VARCHAR(50),
    state        ENUM('NORMAL','WAITING_SERVER_INPUT','CONFIRMING_SERVER') NOT NULL DEFAULT 'NORMAL',
    pending_intent  JSON,
    pending_servers JSON,
    last_question   TEXT,
    last_es_queries JSON,
    last_error_messages JSON,
    last_assistant_summary TEXT,
    created_at   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX idx_user (user_id),
    CONSTRAINT fk_cs_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ─── chat_messages ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chat_messages (
    id                 VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    session_id         VARCHAR(36) NOT NULL,
    role               ENUM('user','assistant') NOT NULL,
    content            LONGTEXT    NOT NULL,
    assistant_metadata JSON,
    trace_id           VARCHAR(50),
    created_at         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_session (session_id),
    CONSTRAINT fk_cm_session FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ─── worker_configs ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS worker_configs (
    id             VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    app_id         VARCHAR(50)  NOT NULL UNIQUE,
    is_enabled     TINYINT(1)   NOT NULL DEFAULT 1,
    file_patterns  JSON         NOT NULL DEFAULT ('["*.txt","*.log"]'),
    schedule_cron  VARCHAR(50)  NOT NULL DEFAULT '*/5 * * * *',
    batch_size     INT          NOT NULL DEFAULT 100,
    created_at     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

-- ─── collector_state ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS collector_state (
    id              VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    app_id          VARCHAR(50) NOT NULL,
    file_path       TEXT        NOT NULL,
    last_byte       BIGINT      NOT NULL DEFAULT 0,
    file_size       BIGINT      NOT NULL DEFAULT 0,
    records_indexed INT         NOT NULL DEFAULT 0,
    last_run_at     DATETIME(6),
    INDEX idx_app_file (app_id, file_path(255))
) ENGINE=InnoDB;

-- ─── Seed data ───────────────────────────────────────────────────────
-- Admin user (password: changeme123)
INSERT IGNORE INTO users (id, username, password_hash, full_name, role, is_active) VALUES
('usr-admin-001', 'admin', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewFzAn1jClD3qBi2', 'System Admin', 'admin', 1);

INSERT IGNORE INTO user_app_permissions (id, user_id, app_id) VALUES
(UUID(), 'usr-admin-001', 'all');

-- Error classifier patterns
INSERT IGNORE INTO error_classifier_patterns (pattern, error_type, severity, priority) VALUES
('(?i)unable to connect|connection attempt failed', 'connection_timeout', 'error',   100),
('ORA-12170|TNS:Connect timeout',                  'oracle_timeout',     'error',    90),
('ORA-00060|deadlock detected',                    'oracle_deadlock',    'critical', 80),
('(?i)smtp|:465',                                  'smtp_error',         'warning',  100),
('ORA-04045',                                      'oracle_recompile',   'warning',  100),
('ORA-',                                           'oracle_error',       'error',    200);
