CREATE TABLE IF NOT EXISTS approval_publication_attempt (
    id BIGINT NOT NULL AUTO_INCREMENT,
    approval_id VARCHAR(36) NOT NULL,
    run_id VARCHAR(36) NOT NULL,
    attempt_no INT NOT NULL,
    status VARCHAR(20) NOT NULL,
    error_message VARCHAR(500) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_publication_attempt_approval (approval_id, attempt_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
