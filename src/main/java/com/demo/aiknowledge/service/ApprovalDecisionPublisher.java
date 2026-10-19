package com.demo.aiknowledge.service;

import com.demo.aiknowledge.entity.AgentApproval;
import com.demo.aiknowledge.mapper.AgentApprovalMapper;
import com.demo.aiknowledge.queue.QueueNames;
import lombok.RequiredArgsConstructor;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class ApprovalDecisionPublisher {

    private final AgentApprovalMapper approvalMapper;
    private final RabbitTemplate rabbitTemplate;
    private final JdbcTemplate jdbcTemplate;

    public boolean publish(AgentApproval approval) {
        Map<String, Object> message = new LinkedHashMap<>();
        message.put("schemaVersion", "1.0");
        message.put("approvalId", approval.getId());
        message.put("runId", approval.getRunId());
        message.put("traceId", approval.getTraceId());
        message.put("documentId", approval.getDocumentId());
        message.put("documentName", approval.getDocumentName());
        message.put("toolName", approval.getToolName());
        message.put("decision", approval.getStatus());
        message.put("decidedAt", approval.getDecidedAt() == null ? null : approval.getDecidedAt().toString());

        try {
            rabbitTemplate.convertAndSend(
                    QueueNames.APPROVAL_EXCHANGE,
                    QueueNames.APPROVAL_DECISION_ROUTING_KEY,
                    message,
                    m -> {
                        m.getMessageProperties().setDeliveryMode(MessageDeliveryMode.PERSISTENT);
                        m.getMessageProperties().setContentType("application/json");
                        return m;
                    });
            recordAttempt(approval, "SUCCESS", null);
            jdbcTemplate.update(
                    "UPDATE agent_approval SET publication_status = 'PUBLISHED' WHERE id = ?",
                    approval.getId());
            return true;
        } catch (RuntimeException e) {
            recordAttempt(approval, "FAILED", e.getMessage());
            jdbcTemplate.update(
                    "UPDATE agent_approval SET publication_status = 'QUEUED' WHERE id = ?",
                    approval.getId());
            return false;
        }
    }

    @Scheduled(fixedDelay = 5000)
    public void republishQueuedDecisions() {
        List<AgentApproval> queued = approvalMapper.selectList(
                new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<AgentApproval>()
                        .in(AgentApproval::getStatus, "APPROVED", "REJECTED")
                        .eq(AgentApproval::getPublicationStatus, "QUEUED")
                        .last("LIMIT 20"));
        queued.forEach(this::publish);
    }

    private void recordAttempt(AgentApproval approval, String status, String error) {
        Integer attemptNo = jdbcTemplate.queryForObject(
                "SELECT COALESCE(MAX(attempt_no), 0) + 1 FROM approval_publication_attempt WHERE approval_id = ?",
                Integer.class,
                approval.getId());
        jdbcTemplate.update(
                """
                INSERT INTO approval_publication_attempt
                    (approval_id, run_id, attempt_no, status, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                approval.getId(),
                approval.getRunId(),
                attemptNo,
                status,
                error == null ? null : error.substring(0, Math.min(500, error.length())),
                LocalDateTime.now());
    }
}
