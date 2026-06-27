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
    syslog_index          VARCHAR(200) NOT NULL DEFAULT 'aiops-txt-logs',
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

-- ─── incidents ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS incidents (
    id              VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    app_id          VARCHAR(50)  NOT NULL,
    title           VARCHAR(255) NOT NULL,
    severity        ENUM('critical','high','medium','low') NOT NULL DEFAULT 'high',
    status          ENUM('open','investigating','resolved','closed') NOT NULL DEFAULT 'open',
    description     TEXT,
    root_cause      TEXT,
    solution        TEXT,
    related_logs    JSON,
    error_patterns  JSON,
    affected_servers JSON,
    source          ENUM('manual','chat_draft','prediction') NOT NULL DEFAULT 'manual',
    chat_session_id VARCHAR(36),
    created_by      VARCHAR(36),
    assigned_to     VARCHAR(36),
    resolved_by     VARCHAR(36),
    solution_at     DATETIME(6),
    solution_by     VARCHAR(36),
    incident_time   DATETIME(6),
    resolved_at     DATETIME(6),
    created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX idx_app_status (app_id, status),
    INDEX idx_created_at (created_at),
    INDEX idx_severity (severity),
    CONSTRAINT fk_inc_created_by FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ─── incident_timeline ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS incident_timeline (
    id           VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    incident_id  VARCHAR(36) NOT NULL,
    user_id      VARCHAR(36),
    action       VARCHAR(100) NOT NULL,
    detail       TEXT,
    metadata     JSON,
    created_at   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_incident (incident_id),
    CONSTRAINT fk_tl_incident FOREIGN KEY (incident_id) REFERENCES incidents(id) ON DELETE CASCADE,
    CONSTRAINT fk_tl_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ─── topology_versions ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS topology_versions (
    id          VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    app_id      VARCHAR(50)  NOT NULL,
    version_name VARCHAR(100) NOT NULL DEFAULT 'v1',
    description TEXT,
    is_active   TINYINT(1)   NOT NULL DEFAULT 1,
    created_by  VARCHAR(36),
    created_at  DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_app_active (app_id, is_active),
    CONSTRAINT fk_tv_user FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ─── topology_nodes ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS topology_nodes (
    id            VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    version_id    VARCHAR(36)  NOT NULL,
    app_id        VARCHAR(50)  NOT NULL,
    node_key      VARCHAR(100) NOT NULL,
    label         VARCHAR(200) NOT NULL,
    node_type     ENUM('service','database','queue','server','external','loadbalancer') NOT NULL DEFAULT 'service',
    ip            VARCHAR(45),
    hostname      VARCHAR(255),
    health_status ENUM('healthy','degraded','down','unknown') NOT NULL DEFAULT 'unknown',
    position_x    FLOAT DEFAULT 0,
    position_y    FLOAT DEFAULT 0,
    metadata      JSON,
    created_at    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at    DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_version_key (version_id, node_key),
    INDEX idx_app (app_id),
    CONSTRAINT fk_tn_version FOREIGN KEY (version_id) REFERENCES topology_versions(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ─── topology_edges ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS topology_edges (
    id               VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    version_id       VARCHAR(36) NOT NULL,
    app_id           VARCHAR(50) NOT NULL,
    source_node_id   VARCHAR(36) NOT NULL,
    target_node_id   VARCHAR(36) NOT NULL,
    relation_type    ENUM('calls','depends_on','replicates','proxies','feeds','monitors') NOT NULL DEFAULT 'calls',
    propagation_prob FLOAT       NOT NULL DEFAULT 0.5,
    weight           FLOAT       NOT NULL DEFAULT 1.0,
    label            VARCHAR(100),
    created_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_edge (version_id, source_node_id, target_node_id, relation_type),
    INDEX idx_source (source_node_id),
    INDEX idx_target (target_node_id),
    CONSTRAINT fk_te_version FOREIGN KEY (version_id) REFERENCES topology_versions(id) ON DELETE CASCADE,
    CONSTRAINT fk_te_source FOREIGN KEY (source_node_id) REFERENCES topology_nodes(id) ON DELETE CASCADE,
    CONSTRAINT fk_te_target FOREIGN KEY (target_node_id) REFERENCES topology_nodes(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ─── prediction_baselines ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS prediction_baselines (
    id           VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    app_id       VARCHAR(50) NOT NULL,
    metric_name  VARCHAR(100) NOT NULL,
    server_ip    VARCHAR(45),
    hour_of_day  TINYINT,
    day_of_week  TINYINT,
    mean_val     DECIMAL(12,4) NOT NULL DEFAULT 0,
    std_val      DECIMAL(12,4) NOT NULL DEFAULT 0,
    p95_val      DECIMAL(12,4),
    sample_count INT          NOT NULL DEFAULT 0,
    ewma_alpha   DECIMAL(5,4) NOT NULL DEFAULT 0.3,
    computed_at  DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_app_metric (app_id, metric_name, server_ip)
) ENGINE=InnoDB;

-- ─── prediction_alerts ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS prediction_alerts (
    id              VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    app_id          VARCHAR(50) NOT NULL,
    server_ip       VARCHAR(45),
    alert_type      VARCHAR(50) NOT NULL,
    signal_group    VARCHAR(10) NOT NULL DEFAULT 'A',
    severity        ENUM('critical','high','medium','low') NOT NULL DEFAULT 'medium',
    status          ENUM('open','acknowledged','resolved','suppressed') NOT NULL DEFAULT 'open',
    title           VARCHAR(255) NOT NULL,
    explanation     TEXT,
    metric_name     VARCHAR(100),
    current_value   DECIMAL(12,4),
    baseline_value  DECIMAL(12,4),
    predicted_at    DATETIME(6),
    confidence      DECIMAL(5,4) DEFAULT 0.5,
    evidence        JSON,
    blast_radius    JSON,
    is_true_positive TINYINT(1),
    resolved_at     DATETIME(6),
    suppressed_until DATETIME(6),
    created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX idx_app_status (app_id, status),
    INDEX idx_created (created_at),
    INDEX idx_server (server_ip)
) ENGINE=InnoDB;

-- ─── prediction_scans ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS prediction_scans (
    id              VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    app_id          VARCHAR(50) NOT NULL,
    scan_at         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    duration_ms     INT,
    alerts_created  INT NOT NULL DEFAULT 0,
    signals_found   INT NOT NULL DEFAULT 0,
    data_quality    DECIMAL(5,4),
    error_message   TEXT,
    INDEX idx_app_scan (app_id, scan_at)
) ENGINE=InnoDB;

-- ─── notification_configs ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notification_configs (
    id                  VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    name                VARCHAR(200) NOT NULL,
    app_id              VARCHAR(50),
    channel             ENUM('email','telegram') NOT NULL,
    schedule_cron       VARCHAR(50)  NOT NULL DEFAULT '0 8 * * *',
    is_enabled          BOOLEAN      NOT NULL DEFAULT TRUE,
    recipients          JSON         NOT NULL,
    report_window_hours INT          NOT NULL DEFAULT 24,
    created_by          VARCHAR(36),
    created_at          DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at          DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX idx_enabled (is_enabled),
    CONSTRAINT fk_nc_user FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ─── notification_logs ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notification_logs (
    id               VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    config_id        VARCHAR(36) NOT NULL,
    channel          VARCHAR(50) NOT NULL,
    status           ENUM('sent','failed') NOT NULL,
    recipients_count INT         NOT NULL DEFAULT 0,
    error_message    TEXT,
    sent_at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_config (config_id),
    INDEX idx_sent_at (sent_at),
    CONSTRAINT fk_nl_config FOREIGN KEY (config_id) REFERENCES notification_configs(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ─── Seed data ───────────────────────────────────────────────────────
-- Admin user (password: changeme123)
INSERT IGNORE INTO users (id, username, password_hash, full_name, role, is_active) VALUES
('usr-admin-001', 'admin', '$2b$12$JnHFLlsWmXbd.ad3IJtpAO9xMgXSv1hWFE153nfJmm.ciZDcP6.Qy', 'System Admin', 'admin', 1);

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
