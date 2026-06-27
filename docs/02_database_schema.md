# Database Schema — MariaDB

## Tổng quan
MariaDB lưu toàn bộ cấu hình động của hệ thống. Không có giá trị nào
của endpoint, index pattern, hay threshold được hardcode trong source code.

---

## Tables

### `users` — Người dùng hệ thống
```sql
CREATE TABLE users (
    id            VARCHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    username      VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,           -- bcrypt
    full_name     VARCHAR(200),
    role          ENUM('admin','engineer','manager') NOT NULL DEFAULT 'engineer',
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

### `user_app_permissions` — Phân quyền theo app
```sql
CREATE TABLE user_app_permissions (
    id         INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id    VARCHAR(36) NOT NULL REFERENCES users(id),
    app_id     VARCHAR(50) NOT NULL,   -- erp | mvs | website | all
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_app (user_id, app_id)
);
```

### `datasource_configs` — Endpoint của từng hệ thống
Đây là bảng quan trọng nhất — mọi URL và credential đều ở đây.
```sql
CREATE TABLE datasource_configs (
    id                    INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    app_id                VARCHAR(50)  NOT NULL UNIQUE, -- erp | mvs | website
    display_name          VARCHAR(200) NOT NULL,

    -- Elasticsearch
    elasticsearch_url     TEXT         NOT NULL,
    elasticsearch_api_key TEXT,                         -- encrypted AES-256
    log_index_pattern     VARCHAR(500) NOT NULL,        -- e.g. erp-*,erp-apm-*
    txt_log_index         VARCHAR(200) NOT NULL DEFAULT 'vst-txt-logs',

    -- Prometheus
    prometheus_url        TEXT,
    prometheus_extra_labels JSON,                       -- {"env":"prod","cluster":"erp"}

    -- Kibana
    kibana_url            TEXT,
    kibana_api_key        TEXT,                         -- encrypted

    -- Alert thresholds (JSON, so admin can add fields without migration)
    alert_thresholds      JSON NOT NULL DEFAULT (JSON_OBJECT(
        'cpu_pct',          85,
        'ram_pct',          90,
        'disk_pct',         85,
        'error_count_1h',   10,
        'error_count_critical_1h', 3,
        'connection_timeout_1h',   10,
        'oracle_deadlock_1h',      3,
        'smtp_error_30m',          5
    )),

    -- TXT log collector watch dirs (JSON array)
    txt_watch_dirs        JSON,                         -- ["/mnt/erp-logs", "/mnt/erp-debug"]

    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

### `server_registry` — Server vật lý theo app
```sql
CREATE TABLE server_registry (
    id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    app_id      VARCHAR(50)  NOT NULL,
    ip          VARCHAR(45)  NOT NULL,           -- IPv4 hoặc IPv6
    hostname    VARCHAR(255) NOT NULL,
    os          VARCHAR(100),
    description TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    added_by    VARCHAR(36)  REFERENCES users(id),
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_app_ip (app_id, ip),
    INDEX idx_app_active (app_id, is_active)
);
```

### `worker_configs` — Cấu hình TXT Log Collector
```sql
CREATE TABLE worker_configs (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    app_id          VARCHAR(50)  NOT NULL REFERENCES datasource_configs(app_id),
    watch_dirs      JSON         NOT NULL,        -- ["/mnt/erp-logs"]
    file_patterns   JSON         NOT NULL DEFAULT ('["*.txt","*.log"]'),
    schedule_cron   VARCHAR(50)  NOT NULL DEFAULT '*/5 * * * *',
    batch_size      INT          NOT NULL DEFAULT 100,
    is_enabled      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

### `collector_state` — State của TXT Collector (last_byte per file)
```sql
CREATE TABLE collector_state (
    id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    app_id        VARCHAR(50)  NOT NULL,
    file_path     VARCHAR(1000) NOT NULL,
    last_byte     BIGINT       NOT NULL DEFAULT 0,
    file_size     BIGINT       NOT NULL DEFAULT 0,
    last_run_at   DATETIME,
    records_indexed INT UNSIGNED DEFAULT 0,
    UNIQUE KEY uq_app_file (app_id, file_path(500)),
    INDEX idx_app_id (app_id)
);
```

### `error_classifier_patterns` — Regex patterns phân loại lỗi
Cho phép admin thêm pattern mới không cần deploy lại.
```sql
CREATE TABLE error_classifier_patterns (
    id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    app_id      VARCHAR(50),             -- NULL = áp dụng cho tất cả
    pattern     VARCHAR(500) NOT NULL,   -- regex
    error_type  VARCHAR(100) NOT NULL,   -- connection_timeout | oracle_deadlock | ...
    severity    ENUM('critical','error','warning') NOT NULL DEFAULT 'error',
    priority    INT NOT NULL DEFAULT 100, -- thấp hơn = ưu tiên match trước
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Seed data
INSERT INTO error_classifier_patterns (pattern, error_type, severity, priority) VALUES
('(?i)unable to connect|connection attempt failed',    'connection_timeout',  'error',    100),
('ORA-12170|TNS:Connect timeout',                      'oracle_timeout',      'error',    90),
('ORA-00060|deadlock detected',                        'oracle_deadlock',     'critical', 80),
('(?i)smtp|:465',                                      'smtp_error',          'warning',  100),
('ORA-04045',                                          'oracle_recompile',    'warning',  100),
('ORA-',                                               'oracle_error',        'error',    200);
```

### `notification_configs` — Cấu hình kênh thông báo
```sql
CREATE TABLE notification_configs (
    id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    app_id      VARCHAR(50),             -- NULL = áp dụng tất cả
    channel     ENUM('sms','email') NOT NULL,
    recipients  JSON NOT NULL,           -- ["0912345678"] hoặc ["ops@vst.com"]
    severity_filter ENUM('critical','error','warning','all') NOT NULL DEFAULT 'error',
    cooldown_minutes INT NOT NULL DEFAULT 30,  -- chống spam
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### `audit_logs` — Lịch sử thay đổi config
```sql
CREATE TABLE audit_logs (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id     VARCHAR(36)  REFERENCES users(id),
    action      VARCHAR(100) NOT NULL,   -- CREATE_SERVER | UPDATE_CONFIG | ...
    entity_type VARCHAR(100) NOT NULL,
    entity_id   VARCHAR(200),
    old_value   JSON,
    new_value   JSON,
    ip_address  VARCHAR(45),
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_created (created_at),
    INDEX idx_user (user_id)
);
```

---

## Seed data mẫu

```sql
-- Default admin user (password: changeme123 — MUST change on first deploy)
INSERT INTO users (id, username, password_hash, full_name, role) VALUES
('usr-admin-001', 'admin', '$2b$12$...bcrypt...', 'System Admin', 'admin');

INSERT INTO user_app_permissions (user_id, app_id) VALUES
('usr-admin-001', 'all');

-- VST ERP datasource
INSERT INTO datasource_configs (
    app_id, display_name,
    elasticsearch_url, log_index_pattern, txt_log_index,
    prometheus_url, kibana_url,
    txt_watch_dirs
) VALUES (
    'erp', 'Hệ thống ERP',
    'http://es-erp.vst.internal:9200',
    'erp-*',
    'vst-txt-logs',
    'http://prometheus.vst.internal:9090',
    'http://kibana.vst.internal:5601',
    '["/mnt/erp-logs", "/mnt/erp-debug"]'
);
```
