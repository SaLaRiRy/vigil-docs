package com.demo.aiknowledge.dto;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class DeletionRequestResult {
    private String approvalId;
    private String runId;
    private String traceId;
    private String state;
    private String message;
}
