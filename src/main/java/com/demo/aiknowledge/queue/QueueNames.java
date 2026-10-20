package com.demo.aiknowledge.queue;

public final class QueueNames {
    public static final String DOCUMENT_EXCHANGE = "agentcraft.document.exchange";
    public static final String DOCUMENT_QUEUE = "agentcraft.document.process.v1";
    public static final String DOCUMENT_RETRY_QUEUE = "agentcraft.document.retry.v1";
    public static final String DOCUMENT_DLQ = "agentcraft.document.dlq.v1";
    public static final String DOCUMENT_ROUTING_KEY = "document.process.v1";
    public static final String DOCUMENT_RETRY_ROUTING_KEY = "document.retry.v1";
    public static final String DOCUMENT_DEAD_ROUTING_KEY = "document.dead.v1";

    public static final String APPROVAL_EXCHANGE = "agentcraft.approval.exchange";
    public static final String APPROVAL_DECISION_QUEUE = "agentcraft.approval.decision.v1";
    public static final String APPROVAL_DECISION_ROUTING_KEY = "approval.decision.v1";

    private QueueNames() {
    }
}
