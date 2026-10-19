package com.demo.aiknowledge.service;

import com.demo.aiknowledge.queue.QueueNames;
import lombok.RequiredArgsConstructor;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class DocumentQueuePublisher {

    private final RabbitTemplate rabbitTemplate;

    public void publish(Long documentId, String storagePath, int attempt) {
        Map<String, Object> message = new LinkedHashMap<>();
        message.put("schemaVersion", "1.0");
        message.put("documentId", documentId);
        message.put("storagePath", storagePath);
        message.put("attempt", attempt);
        message.put("enqueuedAt", Instant.now().toString());

        rabbitTemplate.convertAndSend(
                QueueNames.DOCUMENT_EXCHANGE,
                QueueNames.DOCUMENT_ROUTING_KEY,
                message,
                m -> {
                    m.getMessageProperties().setDeliveryMode(MessageDeliveryMode.PERSISTENT);
                    m.getMessageProperties().setContentType("application/json");
                    return m;
                });
    }
}
