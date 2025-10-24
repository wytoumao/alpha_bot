-- Schema for Alpha Reminder Bot persistence layer

CREATE TABLE IF NOT EXISTS alpha_events (
    id BIGINT UNSIGNED AUTO_INCREMENT COMMENT 'Primary key' PRIMARY KEY,
    token VARCHAR(64) NOT NULL COMMENT 'Token symbol or project identifier',
    start_time DATETIME NULL COMMENT 'Parsed local start time (Asia/Taipei)',
    raw_time VARCHAR(64) NULL COMMENT 'Raw time string extracted from source',
    amount VARCHAR(128) NULL COMMENT 'Parsed amount or allocation info',
    points VARCHAR(64) NULL COMMENT 'Parsed points/score requirement',
    project VARCHAR(128) NULL COMMENT 'Parsed project/display name',
    details_json JSON NOT NULL COMMENT 'Full detail payload as JSON',
    source ENUM('json','dom','db') NOT NULL COMMENT 'Original data origin',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Record update timestamp',
    UNIQUE KEY uk_event_token_raw_time (token, raw_time),
    KEY idx_start_time (start_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Scraped Alpha listing/airdrop events';

CREATE TABLE IF NOT EXISTS alpha_notifications (
    id BIGINT UNSIGNED AUTO_INCREMENT COMMENT 'Primary key' PRIMARY KEY,
    event_id BIGINT UNSIGNED NOT NULL COMMENT 'Foreign key to alpha_events',
    offset_minutes INT NULL COMMENT 'Reminder offset in minutes (NULL for TBA/new item alerts)',
    remind_at DATETIME NOT NULL COMMENT 'Scheduled reminder time (local timezone)',
    channel ENUM('voice','sms','fs','dd','wx','mail') NOT NULL COMMENT 'Planned notification channel',
    status ENUM('pending','sent','failed','skipped') NOT NULL DEFAULT 'pending' COMMENT 'Current task status',
    sent_at DATETIME NULL COMMENT 'Actual send timestamp',
    fail_reason VARCHAR(255) NULL COMMENT 'Reason for failure, if any',
    attempts TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Number of attempts performed',
    metadata JSON NULL COMMENT 'Additional metadata (quiet-mode overrides, retry context, etc.)',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Creation timestamp',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Update timestamp',
    UNIQUE KEY uk_event_offset (event_id, offset_minutes, channel),
    KEY idx_status_remind (status, remind_at),
    KEY idx_event (event_id),
    CONSTRAINT fk_notifications_event
        FOREIGN KEY (event_id) REFERENCES alpha_events (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Scheduled notification tasks generated from events';

CREATE TABLE IF NOT EXISTS alpha_notification_logs (
    id BIGINT UNSIGNED AUTO_INCREMENT COMMENT 'Primary key' PRIMARY KEY,
    notification_id BIGINT UNSIGNED NOT NULL COMMENT 'Foreign key to alpha_notifications',
    attempt_no TINYINT UNSIGNED NOT NULL COMMENT 'Attempt sequence number',
    spug_endpoint VARCHAR(64) NOT NULL COMMENT 'Spug endpoint invoked',
    payload JSON NOT NULL COMMENT 'Request payload sent to Spug',
    response_code INT NULL COMMENT 'HTTP status code returned',
    response_body JSON NULL COMMENT 'Response body from Spug',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Log creation timestamp',
    KEY idx_notification (notification_id),
    CONSTRAINT fk_log_notification
        FOREIGN KEY (notification_id) REFERENCES alpha_notifications (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Detailed notification send logs for auditing';
