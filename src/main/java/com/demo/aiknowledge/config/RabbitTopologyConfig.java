package com.demo.aiknowledge.config;

import com.demo.aiknowledge.queue.QueueNames;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.QueueBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class RabbitTopologyConfig {

    @Bean
    MessageConverter rabbitMessageConverter(ObjectMapper objectMapper) {
        return new Jackson2JsonMessageConverter(objectMapper);
    }

    @Bean
    DirectExchange documentExchange() {
        return new DirectExchange(QueueNames.DOCUMENT_EXCHANGE, true, false);
    }

    @Bean
    DirectExchange approvalExchange() {
        return new DirectExchange(QueueNames.APPROVAL_EXCHANGE, true, false);
    }

    @Bean
    Queue documentQueue() {
        return QueueBuilder.durable(QueueNames.DOCUMENT_QUEUE).build();
    }

    @Bean
    Queue documentRetryQueue() {
        return QueueBuilder.durable(QueueNames.DOCUMENT_RETRY_QUEUE)
                .ttl(1500)
                .deadLetterExchange(QueueNames.DOCUMENT_EXCHANGE)
                .deadLetterRoutingKey(QueueNames.DOCUMENT_ROUTING_KEY)
                .build();
    }

    @Bean
    Queue documentDeadLetterQueue() {
        return QueueBuilder.durable(QueueNames.DOCUMENT_DLQ).build();
    }

    @Bean
    Queue approvalDecisionQueue() {
        return QueueBuilder.durable(QueueNames.APPROVAL_DECISION_QUEUE).build();
    }

    @Bean
    Binding documentBinding() {
        return BindingBuilder.bind(documentQueue()).to(documentExchange()).with(QueueNames.DOCUMENT_ROUTING_KEY);
    }

    @Bean
    Binding documentRetryBinding() {
        return BindingBuilder.bind(documentRetryQueue()).to(documentExchange()).with(QueueNames.DOCUMENT_RETRY_ROUTING_KEY);
    }

    @Bean
    Binding documentDeadBinding() {
        return BindingBuilder.bind(documentDeadLetterQueue()).to(documentExchange()).with(QueueNames.DOCUMENT_DEAD_ROUTING_KEY);
    }

    @Bean
    Binding approvalDecisionBinding() {
        return BindingBuilder.bind(approvalDecisionQueue()).to(approvalExchange())
                .with(QueueNames.APPROVAL_DECISION_ROUTING_KEY);
    }
}
