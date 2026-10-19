package com.demo.aiknowledge.dto;

import lombok.Data;

@Data
public class ApprovalDecisionPayload {
    private String decision;
    private String comment;
}
