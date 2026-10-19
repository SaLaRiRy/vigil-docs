package com.demo.aiknowledge.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("agent_approval")
public class AgentApproval {
    @TableId
    private String id;
    private String runId;
    private String traceId;
    private String requesterId;
    private Long documentId;
    private String documentName;
    private String documentPreviousStatus;
    private String toolName;
    private String toolParametersJson;
    private String riskReason;
    private String status;
    private String publicationStatus;
    private String executionStatus;
    private LocalDateTime executionUpdatedAt;
    private String cleanupStatus;
    private LocalDateTime createdAt;
    private LocalDateTime expiresAt;
    private String reviewerId;
    private LocalDateTime decidedAt;
    private String reviewComment;
}
