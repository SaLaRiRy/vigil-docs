package com.demo.aiknowledge.service;

import com.demo.aiknowledge.entity.AgentApproval;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class ApprovalNotificationService {

    private final Map<Long, SseEmitter> emitters = new ConcurrentHashMap<>();
    private long nextId = 1;

    public SseEmitter subscribe() {
        long emitterId = nextId++;
        SseEmitter emitter = new SseEmitter(30 * 60 * 1000L);
        emitters.put(emitterId, emitter);
        Runnable cleanup = () -> emitters.remove(emitterId);
        emitter.onCompletion(cleanup);
        emitter.onTimeout(cleanup);
        emitter.onError(error -> cleanup.run());
        try {
            emitter.send(SseEmitter.event().name("connected").data(Map.of("status", "connected")));
        } catch (IOException e) {
            cleanup.run();
        }
        return emitter;
    }

    public void notifyPending(AgentApproval approval) {
        Map<String, Object> payload = Map.of(
                "approvalId", approval.getId(),
                "runId", approval.getRunId(),
                "traceId", approval.getTraceId(),
                "documentId", approval.getDocumentId()
        );
        emitters.forEach((id, emitter) -> {
            try {
                emitter.send(SseEmitter.event().name("approval.pending").data(payload));
            } catch (IOException e) {
                emitter.complete();
                emitters.remove(id);
            }
        });
    }
}
