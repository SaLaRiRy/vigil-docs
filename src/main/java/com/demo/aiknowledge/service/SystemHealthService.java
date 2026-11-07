package com.demo.aiknowledge.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.LinkedHashMap;
import java.util.Map;

@Service
public class SystemHealthService {

    private final RestTemplate restTemplate;
    private final String aiServiceUrl;

    public SystemHealthService(
            @Qualifier("systemHealthRestTemplate") RestTemplate restTemplate,
            @Value("${ai.service.url}") String aiServiceUrl) {
        this.restTemplate = restTemplate;
        this.aiServiceUrl = aiServiceUrl;
    }

    public Map<String, Object> getHealth() {
        try {
            ResponseEntity<Map> response = restTemplate.getForEntity(
                    aiServiceUrl + "/runtime-health", Map.class);
            if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
                return response.getBody();
            }
        } catch (Exception ignored) {
            // The admin UI must still receive a structured degradation response.
        }
        return unavailable("无法获取 Python 服务运行状态");
    }

    private Map<String, Object> unavailable(String message) {
        Map<String, Object> vectorIndex = new LinkedHashMap<>();
        vectorIndex.put("status", "UNAVAILABLE");
        vectorIndex.put("message", message);

        Map<String, Object> consumer = new LinkedHashMap<>();
        consumer.put("status", "UNAVAILABLE");
        consumer.put("queueDepth", 0);
        consumer.put("consumerCount", 0);
        consumer.put("pendingCount", 0);
        consumer.put("processingCount", 0);
        consumer.put("stalePendingCount", 0);
        consumer.put("maxProcessingAttempts", 0);
        consumer.put("message", message);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("vectorIndex", vectorIndex);
        result.put("documentConsumer", consumer);
        return result;
    }
}
