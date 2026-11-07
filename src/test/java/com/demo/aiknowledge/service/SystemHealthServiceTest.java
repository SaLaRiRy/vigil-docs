package com.demo.aiknowledge.service;

import com.demo.aiknowledge.config.RestTemplateConfig;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import java.util.Map;
import java.lang.reflect.Field;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class SystemHealthServiceTest {

    @Test
    void healthClientUsesAShortReadTimeout() throws Exception {
        RestTemplate client = new RestTemplateConfig().systemHealthRestTemplate();
        SimpleClientHttpRequestFactory factory =
                (SimpleClientHttpRequestFactory) client.getRequestFactory();

        Field connectTimeout = SimpleClientHttpRequestFactory.class
                .getDeclaredField("connectTimeout");
        Field readTimeout = SimpleClientHttpRequestFactory.class
                .getDeclaredField("readTimeout");
        connectTimeout.setAccessible(true);
        readTimeout.setAccessible(true);

        assertThat(connectTimeout.get(factory)).isEqualTo(2000);
        assertThat(readTimeout.get(factory)).isEqualTo(5000);
    }

    @Test
    void returnsPythonRuntimeHealthContract() {
        RestTemplate restTemplate = mock(RestTemplate.class);
        Map<String, Object> health = Map.of(
                "vectorIndex", Map.of("status", "HEALTHY"),
                "documentConsumer", Map.of("status", "DEGRADED")
        );
        when(restTemplate.getForEntity("http://ai/api/runtime-health", Map.class))
                .thenReturn(ResponseEntity.ok(health));

        SystemHealthService service =
                new SystemHealthService(restTemplate, "http://ai/api");

        assertThat(service.getHealth()).isEqualTo(health);
    }

    @Test
    void pythonFailureReturnsExplicitUnavailableState() {
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.getForEntity("http://ai/api/runtime-health", Map.class))
                .thenThrow(new RestClientException("offline"));

        SystemHealthService service =
                new SystemHealthService(restTemplate, "http://ai/api");

        Map<String, Object> health = service.getHealth();
        assertThat(((Map<?, ?>) health.get("vectorIndex")).get("status"))
                .isEqualTo("UNAVAILABLE");
        assertThat(((Map<?, ?>) health.get("documentConsumer")).get("status"))
                .isEqualTo("UNAVAILABLE");
    }
}
