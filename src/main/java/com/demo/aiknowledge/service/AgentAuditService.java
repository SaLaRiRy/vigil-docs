package com.demo.aiknowledge.service;

import com.demo.aiknowledge.entity.AgentAuditEvent;
import com.demo.aiknowledge.mapper.AgentAuditEventMapper;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class AgentAuditService {

    private final AgentAuditEventMapper auditEventMapper;
    private final ObjectMapper objectMapper;

    public void record(String runId, String traceId, String eventType, Map<String, Object> payload) {
        AgentAuditEvent event = new AgentAuditEvent();
        event.setRunId(runId);
        event.setTraceId(traceId);
        event.setEventType(eventType);
        try {
            event.setPayloadJson(objectMapper.writeValueAsString(payload));
        } catch (JsonProcessingException e) {
            event.setPayloadJson("{\"serializationError\":true}");
        }
        event.setCreatedAt(LocalDateTime.now());
        auditEventMapper.insert(event);
    }
}
