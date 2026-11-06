package com.demo.aiknowledge.service;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.List;

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

    public List<Long> findStalePendingIds(int staleAfterMinutes, int limit) {
        return jdbcTemplate.queryForList("""
                SELECT d.id
                FROM knowledge_doc d
                LEFT JOIN document_processing p ON p.doc_id = d.id
                WHERE d.status = 'PENDING'
                  AND d.create_time < DATE_SUB(NOW(), INTERVAL ? MINUTE)
                  AND COALESCE(p.attempts, 0) = 0
                ORDER BY d.id
                LIMIT ?
                """, Long.class, staleAfterMinutes, limit);
    }
}
