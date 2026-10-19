package com.demo.aiknowledge.config;

import lombok.RequiredArgsConstructor;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class MvpSchemaInitializer implements ApplicationRunner {

    private final JdbcTemplate jdbcTemplate;

    @Override
    public void run(ApplicationArguments args) {
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS document_processing (
                    doc_id BIGINT NOT NULL PRIMARY KEY,
                    attempts INT NOT NULL DEFAULT 0,
                    last_error VARCHAR(500) NULL,
                    dead_lettered TINYINT(1) NOT NULL DEFAULT 0,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS agent_approval (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    run_id VARCHAR(36) NOT NULL,
                    trace_id VARCHAR(64) NOT NULL,
                    requester_id VARCHAR(36) NOT NULL,
                    document_id BIGINT NOT NULL,
                    document_name VARCHAR(255) NOT NULL,
                    document_previous_status VARCHAR(20) NOT NULL,
                    tool_name VARCHAR(100) NOT NULL,
                    tool_parameters_json TEXT NOT NULL,
                    risk_reason VARCHAR(500) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    publication_status VARCHAR(20) NOT NULL DEFAULT 'NOT_REQUIRED',
                    execution_status VARCHAR(20) NOT NULL DEFAULT 'NOT_STARTED',
                    cleanup_status VARCHAR(20) NOT NULL DEFAULT 'NOT_STARTED',
                    created_at DATETIME NOT NULL,
                    expires_at DATETIME NOT NULL,
                    reviewer_id VARCHAR(36) NULL,
                    decided_at DATETIME NULL,
                    review_comment VARCHAR(1000) NULL,
                    UNIQUE KEY uk_approval_run_tool_document (run_id, tool_name, document_id),
                    KEY idx_approval_pending (status, expires_at),
                    KEY idx_approval_publication (status, publication_status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS agent_audit_event (
                    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    run_id VARCHAR(36) NOT NULL,
                    trace_id VARCHAR(64) NOT NULL,
                    event_type VARCHAR(80) NOT NULL,
                    payload_json TEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    KEY idx_audit_run (run_id, created_at),
                    KEY idx_audit_trace (trace_id, created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS approval_publication_attempt (
                    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    approval_id VARCHAR(36) NOT NULL,
                    run_id VARCHAR(36) NOT NULL,
                    attempt_no INT NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    error_message VARCHAR(500) NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    KEY idx_publication_attempt_approval (approval_id, attempt_no)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
    }
}
