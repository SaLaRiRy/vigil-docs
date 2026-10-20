package com.demo.aiknowledge.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("agent_audit_event")
public class AgentAuditEvent {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String runId;
    private String traceId;
    private String eventType;
    private String payloadJson;
    private LocalDateTime createdAt;
}
