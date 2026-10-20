package com.demo.aiknowledge.dto;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class ApprovalDecisionResult {
    private String approvalId;
    private String runId;
    private String status;
    private boolean idempotentReplay;
    private String publicationStatus;
}
