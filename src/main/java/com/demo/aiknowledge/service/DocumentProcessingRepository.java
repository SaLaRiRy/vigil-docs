package com.demo.aiknowledge.service;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class DocumentProcessingRepository {

    private final JdbcTemplate jdbcTemplate;

    public void initialize(Long documentId) {
        jdbcTemplate.update("""
                INSERT INTO document_processing (doc_id, attempts, dead_lettered)
                VALUES (?, 0, 0)
                ON DUPLICATE KEY UPDATE attempts = 0, dead_lettered = 0, last_error = NULL
                """, documentId);
    }

    public void prepareRetry(Long documentId) {
        jdbcTemplate.update(
                "UPDATE document_processing SET attempts = 0, dead_lettered = 0, last_error = NULL WHERE doc_id = ?",
                documentId);
    }
}
