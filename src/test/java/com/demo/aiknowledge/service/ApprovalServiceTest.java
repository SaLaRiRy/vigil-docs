package com.demo.aiknowledge.service;

import com.demo.aiknowledge.entity.AgentApproval;
import com.demo.aiknowledge.entity.AgentRun;
import com.demo.aiknowledge.entity.KnowledgeDoc;
import com.demo.aiknowledge.mapper.AgentApprovalMapper;
import com.demo.aiknowledge.mapper.AgentRunMapper;
import com.demo.aiknowledge.mapper.AgentStepMapper;
import com.demo.aiknowledge.mapper.KnowledgeDocMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.jdbc.core.JdbcTemplate;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ApprovalServiceTest {

    @Mock private AgentApprovalMapper approvalMapper;
    @Mock private AgentRunMapper runMapper;
    @Mock private AgentStepMapper stepMapper;
    @Mock private KnowledgeDocMapper docMapper;
    @Mock private AgentAuditService auditService;
    @Mock private ApprovalNotificationService notificationService;
    @Mock private ApprovalDecisionPublisher decisionPublisher;
    @Mock private JdbcTemplate jdbcTemplate;

    @Test
    void createsDurableApprovalWithoutInvokingDeletion() {
        KnowledgeDoc document = document("COMPLETED");
        when(docMapper.selectById(7L)).thenReturn(document);
        ApprovalService service = service();

        var result = service.requestDeletion(7L, "Delete the selected document", "6");

        assertThat(result.getState()).isEqualTo("WAITING_APPROVAL");
        assertThat(result.getApprovalId()).isNotBlank();
        assertThat(document.getStatus()).isEqualTo("WAITING_APPROVAL");
        ArgumentCaptor<AgentApproval> approvalCaptor = ArgumentCaptor.forClass(AgentApproval.class);
        verify(approvalMapper).insert(approvalCaptor.capture());
        AgentApproval approval = approvalCaptor.getValue();
        assertThat(approval.getStatus()).isEqualTo("PENDING");
        assertThat(Duration.between(approval.getCreatedAt(), approval.getExpiresAt()))
                .isEqualTo(Duration.ofMinutes(30));
        verify(notificationService).notifyPending(approval);
    }

    @Test
    void expiresPendingApprovalAndRestoresDocumentState() {
        AgentApproval approval = new AgentApproval();
        approval.setId("approval-1");
        approval.setRunId("run-1");
        approval.setTraceId("trace-1");
        approval.setDocumentId(7L);
        approval.setDocumentPreviousStatus("COMPLETED");
        approval.setStatus("PENDING");
        approval.setExpiresAt(LocalDateTime.now().minusMinutes(1));
        when(approvalMapper.selectList(any())).thenReturn(List.of(approval));
        when(jdbcTemplate.update(any(String.class), any(LocalDateTime.class), any(String.class))).thenReturn(1);
        KnowledgeDoc document = document("WAITING_APPROVAL");
        when(docMapper.selectById(7L)).thenReturn(document);
        AgentRun run = new AgentRun();
        when(runMapper.selectByRunId("run-1")).thenReturn(run);

        service().expireStaleApprovals();

        assertThat(document.getStatus()).isEqualTo("COMPLETED");
        assertThat(run.getStatus()).isEqualTo("failed");
        verify(auditService).record(
                org.mockito.ArgumentMatchers.eq("run-1"),
                org.mockito.ArgumentMatchers.eq("trace-1"),
                org.mockito.ArgumentMatchers.eq("APPROVAL_EXPIRED"),
                any());
    }

    private ApprovalService service() {
        return new ApprovalService(
                approvalMapper,
                runMapper,
                stepMapper,
                docMapper,
                new PromptInjectionGuardrail(),
                auditService,
                notificationService,
                decisionPublisher,
                new ObjectMapper().findAndRegisterModules(),
                jdbcTemplate);
    }

    private KnowledgeDoc document(String status) {
        KnowledgeDoc document = new KnowledgeDoc();
        document.setId(7L);
        document.setDocName("fixture.txt");
        document.setStatus(status);
        return document;
    }
}
