package com.demo.aiknowledge.service;

import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Locale;

@Service
public class PromptInjectionGuardrail {

    private static final List<String> PATTERNS = List.of(
            "ignore previous instructions",
            "ignore all previous",
            "system prompt",
            "bypass approval",
            "approve automatically",
            "disable guardrail",
            "jailbreak",
            "忽略之前",
            "忽略以上",
            "绕过审批",
            "自动批准",
            "系统提示词"
    );

    public boolean isBlocked(String instruction) {
        if (instruction == null || instruction.isBlank()) {
            return false;
        }
        String normalized = instruction.toLowerCase(Locale.ROOT);
        return PATTERNS.stream().anyMatch(normalized::contains);
    }
}
