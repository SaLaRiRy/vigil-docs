package com.demo.aiknowledge.service.impl;

import com.demo.aiknowledge.entity.KnowledgeDoc;
import com.demo.aiknowledge.mapper.DocViewLogMapper;
import com.demo.aiknowledge.mapper.KnowledgeDocMapper;
import com.demo.aiknowledge.service.AiService;
import com.demo.aiknowledge.service.DocumentProcessingRepository;
import com.demo.aiknowledge.service.DocumentQueuePublisher;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.multipart.MultipartFile;

import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class KnowledgeServiceImplTest {

    @Mock
    private KnowledgeDocMapper docMapper;
    @Mock
    private DocViewLogMapper viewLogMapper;
    @Mock
    private AiService aiService;
    @Mock
    private DocumentQueuePublisher publisher;
    @Mock
    private DocumentProcessingRepository processingRepository;
    @Mock
    private MultipartFile file;

    @TempDir
    Path uploadDir;

    @Test
    void uploadPublishesWithoutCallingTheInProcessParser() throws Exception {
        KnowledgeServiceImpl service = service();
        when(file.getOriginalFilename()).thenReturn("valid.txt");
        doNothing().when(file).transferTo(any(java.io.File.class));
        doAnswer(invocation -> {
            KnowledgeDoc doc = invocation.getArgument(0);
            doc.setId(42L);
            return 1;
        }).when(docMapper).insert(any(KnowledgeDoc.class));

        KnowledgeDoc result = service.uploadDoc(file, 1L);

        assertThat(result.getStatus()).isEqualTo("PENDING");
        verify(processingRepository).initialize(42L);
        verify(publisher).publish(42L, result.getFilePath(), 1);
        verify(aiService, org.mockito.Mockito.never()).parseDocument(any(), any());
    }

    @Test
    void publishFailureLeavesDocumentInFailedState() throws Exception {
        KnowledgeServiceImpl service = service();
        when(file.getOriginalFilename()).thenReturn("valid.txt");
        doNothing().when(file).transferTo(any(java.io.File.class));
        doAnswer(invocation -> {
            KnowledgeDoc doc = invocation.getArgument(0);
            doc.setId(43L);
            return 1;
        }).when(docMapper).insert(any(KnowledgeDoc.class));
        doThrow(new IllegalStateException("broker unavailable"))
                .when(publisher).publish(any(), any(), any(Integer.class));

        KnowledgeDoc result = service.uploadDoc(file, null);

        assertThat(result.getStatus()).isEqualTo("FAILED");
        assertThat(result.getErrorMessage()).isNotBlank();
        verify(docMapper).updateById(result);
    }

    @Test
    void duplicateRetryOfAnAlreadyQueuedDocumentIsANoOp() {
        KnowledgeServiceImpl service = service();
        KnowledgeDoc document = new KnowledgeDoc();
        document.setId(44L);
        document.setStatus("PENDING");
        document.setFilePath("D:/uploads/valid.txt");
        when(docMapper.selectById(44L)).thenReturn(document);

        service.retryProcessing(44L);

        verify(publisher, org.mockito.Mockito.never()).publish(any(), any(), any(Integer.class));
    }

    private KnowledgeServiceImpl service() {
        KnowledgeServiceImpl service = new KnowledgeServiceImpl(
                docMapper,
                viewLogMapper,
                aiService,
                publisher,
                processingRepository);
        ReflectionTestUtils.setField(service, "uploadDir", uploadDir.toString());
        return service;
    }
}
