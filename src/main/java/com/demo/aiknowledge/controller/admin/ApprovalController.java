package com.demo.aiknowledge.controller.admin;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.demo.aiknowledge.common.Result;
import com.demo.aiknowledge.dto.ApprovalDecisionPayload;
import com.demo.aiknowledge.dto.ApprovalDecisionResult;
import com.demo.aiknowledge.entity.AgentApproval;
import com.demo.aiknowledge.entity.AgentAuditEvent;
import com.demo.aiknowledge.mapper.AgentAuditEventMapper;
import com.demo.aiknowledge.service.ApprovalNotificationService;
import com.demo.aiknowledge.service.ApprovalService;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.List;

@RestController
@RequestMapping("/api/admin/approvals")
@RequiredArgsConstructor
public class ApprovalController {

    private final ApprovalService approvalService;
    private final ApprovalNotificationService notificationService;
    private final AgentAuditEventMapper auditEventMapper;

    @GetMapping("/pending")
    public Result<List<AgentApproval>> pending() {
        return Result.success(approvalService.pendingApprovals());
    }

    @GetMapping("/{approvalId}")
    public Result<AgentApproval> get(@PathVariable String approvalId) {
        return Result.success(approvalService.getApproval(approvalId));
    }

    @PostMapping("/{approvalId}/decision")
    public Result<ApprovalDecisionResult> decide(
            @PathVariable String approvalId,
            @RequestBody ApprovalDecisionPayload payload,
            Authentication authentication) {
        return Result.success(approvalService.decide(
                approvalId,
                payload.getDecision(),
                authentication.getName(),
                payload.getComment()));
    }

    @GetMapping("/stream")
    public SseEmitter stream() {
        return notificationService.subscribe();
    }

    @GetMapping("/{approvalId}/audit")
    public Result<List<AgentAuditEvent>> audit(@PathVariable String approvalId) {
        AgentApproval approval = approvalService.getApproval(approvalId);
        return Result.success(auditEventMapper.selectList(
                new LambdaQueryWrapper<AgentAuditEvent>()
                        .eq(AgentAuditEvent::getRunId, approval.getRunId())
                        .orderByAsc(AgentAuditEvent::getCreatedAt)
                        .orderByAsc(AgentAuditEvent::getId)));
    }
}
