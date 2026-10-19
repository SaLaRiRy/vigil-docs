package com.demo.aiknowledge.service;

import com.demo.aiknowledge.queue.QueueNames;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.amqp.core.MessagePostProcessor;
import org.springframework.amqp.rabbit.core.RabbitTemplate;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
class DocumentQueuePublisherTest {

    @Mock
    private RabbitTemplate rabbitTemplate;

    @InjectMocks
    private DocumentQueuePublisher publisher;

    @Test
    void publishesTheVersionedContractExpectedByPython() {
        publisher.publish(42L, "D:/uploads/example.txt", 1);

        ArgumentCaptor<Object> payload = ArgumentCaptor.forClass(Object.class);
        verify(rabbitTemplate).convertAndSend(
                eq(QueueNames.DOCUMENT_EXCHANGE),
                eq(QueueNames.DOCUMENT_ROUTING_KEY),
                payload.capture(),
                any(MessagePostProcessor.class));

        @SuppressWarnings("unchecked")
        Map<String, Object> message = (Map<String, Object>) payload.getValue();
        assertThat(message)
                .containsEntry("schemaVersion", "1.0")
                .containsEntry("documentId", 42L)
                .containsEntry("storagePath", "D:/uploads/example.txt")
                .containsEntry("attempt", 1);
        assertThat(message.get("enqueuedAt")).isNotNull();
    }
}
