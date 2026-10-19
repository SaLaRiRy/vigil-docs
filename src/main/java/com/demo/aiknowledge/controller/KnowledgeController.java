package com.demo.aiknowledge.controller;

import com.demo.aiknowledge.common.Result;
import com.demo.aiknowledge.dto.DeletionRequestPayload;
import com.demo.aiknowledge.dto.DeletionRequestResult;
import com.demo.aiknowledge.entity.KnowledgeDoc;
import com.demo.aiknowledge.service.ApprovalService;
import com.demo.aiknowledge.service.KnowledgeService;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

@RestController
@RequestMapping("/api/knowledge")
@RequiredArgsConstructor
public class KnowledgeController {

    private final KnowledgeService knowledgeService;
    private final ApprovalService approvalService;

    @PostMapping("/upload")
    public Result<KnowledgeDoc> upload(@RequestParam("file") MultipartFile file, @RequestParam(required = false) Long categoryId) {
        return Result.success(knowledgeService.uploadDoc(file, categoryId));
    }

    @GetMapping("/list")
    public Result<List<KnowledgeDoc>> list(@RequestParam(required = false) Long categoryId) {
        return Result.success(knowledgeService.listDocs(categoryId));
    }

    @DeleteMapping("/{id}")
    public Result<String> delete(@PathVariable Long id) {
        return Result.error(403, "Direct deletion is disabled; submit a deletion request for approval");
    }

    @PostMapping("/{id}/deletion-request")
    public Result<DeletionRequestResult> requestDeletion(
            @PathVariable Long id,
            @RequestBody(required = false) DeletionRequestPayload payload,
            Authentication authentication) {
        String instruction = payload == null ? "Delete the explicitly selected document" : payload.getInstruction();
        return Result.success(approvalService.requestDeletion(id, instruction, authentication.getName()));
    }

    @GetMapping("/view/{id}")
    public Result<KnowledgeDoc> view(@PathVariable Long id, @RequestParam Long userId) {
        return Result.success(knowledgeService.viewDoc(id, userId));
    }
}
