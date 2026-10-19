package com.demo.aiknowledge.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.demo.aiknowledge.dto.ApprovalDecisionResult;
import com.demo.aiknowledge.dto.DeletionRequestResult;
import com.demo.aiknowledge.entity.AgentApproval;
import com.demo.aiknowledge.entity.AgentRun;
import com.demo.aiknowledge.entity.AgentStep;
import com.demo.aiknowledge.entity.KnowledgeDoc;
import com.demo.aiknowledge.mapper.AgentApprovalMapper;
import com.demo.aiknowledge.mapper.AgentRunMapper;
import com.demo.aiknowledge.mapper.AgentStepMapper;
import com.demo.aiknowledge.mapper.KnowledgeDocMapper;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class ApprovalService {

    private static final String TOOL_NAME = "delete_document";

    private final AgentApprovalMapper approvalMapper;
    private final AgentRunMapper runMapper;
    private final AgentStepMapper stepMapper;
    private final KnowledgeDocMapper knowledgeDocMapper;
    private final PromptInjectionGuardrail guardrail;
    private final AgentAuditService auditService;
    private final ApprovalNotificationService notificationService;
    private final ApprovalDecisionPublisher decisionPublisher;
    private final ObjectMapper objectMapper;
    private final JdbcTemplate jdbcTemplate;

    @Transactional
    public DeletionRequestResult requestDeletion(Long documentId, String instruction, String requesterId) {
        KnowledgeDoc document = knowledgeDocMapper.selectById(documentId);
        if (document == null) {
            throw new IllegalArgumentException("Document not found");
        }
        if ("DELETED".equals(document.getStatus())) {
            throw new IllegalStateException("Document is already deleted");
        }

        String runId = UUID.randomUUID().toString();
        String traceId = UUID.randomUUID().toString();
        if (guardrail.isBlocked(instruction)) {
            AgentRun run = createRun(runId, traceId, requesterId, documentId, "failed", instruction);
            run.setEndTime(LocalDateTime.now());
            run.setErrorMessage("Prompt injection attempt refused");
            runMapper.insert(run);
            addStep(runId, "guardrail_validation", "failed", Map.of("blocked", true, "rule", "prompt_injection"));
            auditService.record(runId, traceId, "GUARDRAIL_BLOCKED", Map.of(
                    "documentId", documentId,
                    "requesterId", requesterId,
                    "decision", "refused"
            ));
            return DeletionRequestResult.builder()
                    .runId(runId)
                    .traceId(traceId)
                    .state("REFUSED")
                    .message("This instruction attempts to bypass the approval control and was refused.")
                    .build();
        }

        String approvalId = UUID.randomUUID().toString();
        LocalDateTime now = LocalDateTime.now();
        AgentRun run = createRun(runId, traceId, requesterId, documentId, "waiting_approval", instruction);
        runMapper.insert(run);
        addStep(runId, "guardrail_validation", "success", Map.of("blocked", false));
        addStep(runId, "risk_classification", "success", Map.of("risk", "high", "tool", TOOL_NAME));
        addStep(runId, "approval_wait", "success", Map.of("approvalId", approvalId));

        AgentApproval approval = new AgentApproval();
        approval.setId(approvalId);
        approval.setRunId(runId);
        approval.setTraceId(traceId);
        approval.setRequesterId(requesterId);
        approval.setDocumentId(documentId);
        approval.setDocumentName(document.getDocName());
        approval.setDocumentPreviousStatus(document.getStatus());
        approval.setToolName(TOOL_NAME);
        try {
            approval.setToolParametersJson(objectMapper.writeValueAsString(Map.of("documentId", documentId)));
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Unable to persist sanitized tool parameters", e);
        }
        approval.setRiskReason("Permanent document deletion removes its file and vector index.");
        approval.setStatus("PENDING");
        approval.setPublicationStatus("NOT_REQUIRED");
        approval.setExecutionStatus("NOT_STARTED");
        approval.setCleanupStatus("NOT_STARTED");
        approval.setCreatedAt(now);
        approval.setExpiresAt(now.plusMinutes(30));
        approvalMapper.insert(approval);

        document.setStatus("WAITING_APPROVAL");
        document.setErrorMessage(null);
        knowledgeDocMapper.updateById(document);
        auditService.record(runId, traceId, "APPROVAL_CREATED", Map.of(
                "approvalId", approvalId,
                "documentId", documentId,
                "tool", TOOL_NAME
        ));
        notificationService.notifyPending(approval);
        return DeletionRequestResult.builder()
                .approvalId(approvalId)
                .runId(runId)
                .traceId(traceId)
                .state("WAITING_APPROVAL")
                .message("Deletion is waiting for administrator approval.")
                .build();
    }

    public List<AgentApproval> pendingApprovals() {
        expireStaleApprovals();
        return approvalMapper.selectList(new LambdaQueryWrapper<AgentApproval>()
                .eq(AgentApproval::getStatus, "PENDING")
                .orderByAsc(AgentApproval::getCreatedAt));
    }

    public AgentApproval getApproval(String approvalId) {
        expireStaleApprovals();
        AgentApproval approval = approvalMapper.selectById(approvalId);
        if (approval == null) {
            throw new IllegalArgumentException("Approval not found");
        }
        return approval;
    }

    @Transactional
    public ApprovalDecisionResult decide(String approvalId, String requestedDecision,
                                         String reviewerId, String comment) {
        expireStaleApprovals();
        AgentApproval approval = approvalMapper.selectById(approvalId);
        if (approval == null) {
            throw new IllegalArgumentException("Approval not found");
        }

        String targetStatus = switch (requestedDecision == null ? "" : requestedDecision.toUpperCase()) {
            case "APPROVE", "APPROVED" -> "APPROVED";
            case "REJECT", "REJECTED" -> "REJECTED";
            default -> throw new IllegalArgumentException("Decision must be APPROVE or REJECT");
        };
        if (targetStatus.equals(approval.getStatus())) {
            return ApprovalDecisionResult.builder()
                    .approvalId(approval.getId())
                    .runId(approval.getRunId())
                    .status(approval.getStatus())
                    .publicationStatus(approval.getPublicationStatus())
                    .idempotentReplay(true)
                    .build();
        }
        if (!"PENDING".equals(approval.getStatus())) {
            throw new IllegalStateException("Approval is no longer pending");
        }

        LocalDateTime decidedAt = LocalDateTime.now();
        int changed = jdbcTemplate.update(
                """
                UPDATE agent_approval
                SET status = ?, reviewer_id = ?, decided_at = ?, review_comment = ?,
                    publication_status = 'QUEUED'
                WHERE id = ? AND status = 'PENDING'
                """,
                targetStatus,
                reviewerId,
                decidedAt,
                trim(comment, 1000),
                approvalId);
        if (changed == 0) {
            AgentApproval latest = approvalMapper.selectById(approvalId);
            return ApprovalDecisionResult.builder()
                    .approvalId(latest.getId())
                    .runId(latest.getRunId())
                    .status(latest.getStatus())
                    .publicationStatus(latest.getPublicationStatus())
                    .idempotentReplay(true)
                    .build();
        }

        approval.setStatus(targetStatus);
        approval.setReviewerId(reviewerId);
        approval.setDecidedAt(decidedAt);
        approval.setReviewComment(comment);
        approval.setPublicationStatus("QUEUED");

        AgentRun run = runMapper.selectByRunId(approval.getRunId());
        if ("REJECTED".equals(targetStatus)) {
            KnowledgeDoc document = knowledgeDocMapper.selectById(approval.getDocumentId());
            if (document != null && "WAITING_APPROVAL".equals(document.getStatus())) {
                document.setStatus(approval.getDocumentPreviousStatus());
                knowledgeDocMapper.updateById(document);
            }
            if (run != null) {
                run.setStatus("completed");
                run.setEndTime(decidedAt);
                run.setOutput("Deletion rejected; no destructive tool was invoked.");
                runMapper.updateById(run);
            }
            addStep(approval.getRunId(), "approval_decision", "success", Map.of("status", targetStatus));
        } else if (run != null) {
            addStep(approval.getRunId(), "approval_decision", "success", Map.of("status", targetStatus));
        }

        auditService.record(approval.getRunId(), approval.getTraceId(), "APPROVAL_DECIDED", Map.of(
                "approvalId", approvalId,
                "decision", targetStatus,
                "reviewerId", reviewerId
        ));
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    decisionPublisher.publish(approval);
                }
            });
        } else {
            decisionPublisher.publish(approval);
        }
        AgentApproval published = approvalMapper.selectById(approvalId);
        return ApprovalDecisionResult.builder()
                .approvalId(approvalId)
                .runId(approval.getRunId())
                .status(published.getStatus())
                .publicationStatus(published.getPublicationStatus())
                .idempotentReplay(false)
                .build();
    }

    @Scheduled(fixedDelay = 60000)
    @Transactional
    public void expireStaleApprovals() {
        List<AgentApproval> stale = approvalMapper.selectList(new LambdaQueryWrapper<AgentApproval>()
                .eq(AgentApproval::getStatus, "PENDING")
                .le(AgentApproval::getExpiresAt, LocalDateTime.now()));
        for (AgentApproval approval : stale) {
            int changed = jdbcTemplate.update(
                    "UPDATE agent_approval SET status = 'EXPIRED', decided_at = ? WHERE id = ? AND status = 'PENDING'",
                    LocalDateTime.now(),
                    approval.getId());
            if (changed == 0) {
                continue;
            }
            KnowledgeDoc document = knowledgeDocMapper.selectById(approval.getDocumentId());
            if (document != null && "WAITING_APPROVAL".equals(document.getStatus())) {
                document.setStatus(approval.getDocumentPreviousStatus());
                knowledgeDocMapper.updateById(document);
            }
            AgentRun run = runMapper.selectByRunId(approval.getRunId());
            if (run != null) {
                run.setStatus("failed");
                run.setEndTime(LocalDateTime.now());
                run.setErrorMessage("Approval expired");
                runMapper.updateById(run);
            }
            auditService.record(approval.getRunId(), approval.getTraceId(), "APPROVAL_EXPIRED", Map.of(
                    "approvalId", approval.getId()
            ));
        }
    }

    private AgentRun createRun(String runId, String traceId, String requesterId,
                               Long documentId, String status, String instruction) {
        LocalDateTime now = LocalDateTime.now();
        AgentRun run = new AgentRun();
        run.setId(UUID.randomUUID().toString());
        run.setRunId(runId);
        run.setTraceId(traceId);
        run.setUserId(requesterId);
        run.setStatus(status);
        run.setGoal("Delete document " + documentId + " after explicit approval");
        run.setInput(instruction == null ? "" : truncate(instruction, 2000));
        run.setStartTime(now);
        run.setCreatedAt(now);
        return run;
    }

    private void addStep(String runId, String name, String status, Map<String, Object> output) {
        LocalDateTime now = LocalDateTime.now();
        AgentStep step = new AgentStep();
        step.setId(UUID.randomUUID().toString());
        step.setRunId(runId);
        step.setStepType("tool_call");
        step.setStepName(name);
        step.setStatus(status);
        step.setInput("{}");
        try {
            step.setOutput(objectMapper.writeValueAsString(output));
        } catch (JsonProcessingException e) {
            step.setOutput("{}");
        }
        step.setStartTime(now);
        step.setEndTime(now);
        step.setCreatedAt(now);
        step.setDurationMs(0L);
        stepMapper.insert(step);
    }

    private String truncate(String value, int maxLength) {
        return value == null ? null : value.substring(0, Math.min(maxLength, value.length()));
    }

    private String trim(String value, int maxLength) {
        return value == null ? null : truncate(value, maxLength);
    }
}
