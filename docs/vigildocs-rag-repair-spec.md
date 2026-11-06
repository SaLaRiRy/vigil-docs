# VigilDocs RAG 检索与异步处理修复规格

> 状态：待发布到 GitHub Issue  
> Triage：`ready-for-agent`  
> 本文件是 `$to-spec` 生成的修理清单；在发布前不执行修复。

## Problem Statement

用户上传文档后，VigilDocs 聊天仍然反复提示知识库没有相关内容，或者只使用大模型自身知识回答。管理端还会出现页面持续“加载中”、列表初始显示 0 条、上传文档长期停留在“待处理”的情况。用户无法判断究竟是知识库确实没有内容、文档尚未处理、检索索引不可用，还是后端服务正在等待。

当前已确认的核心问题是：向量索引由一种 embedding 模型构建，而运行时使用另一种维度的 embedding 模型；检索异常又被转换成空结果。即便只修复维度，真实知识也不在索引中，且 FAISS 距离阈值方向错误会继续过滤掉正确结果。异步文档处理还缺少可见的运行状态，导致待处理文档与失效 consumer 难以区分。

## Solution

修复 RAG 检索链路，使知识库问答只从健康、可检索且归属明确的文档中返回答案和引用；当索引不可用时明确报告故障，而不是伪装成“知识库无内容”。同时提供安全、可审计、可回滚的索引检查与重建流程，恢复待处理文档的处理链路，并让管理员能够区分“正在加载”“没有数据”和“服务异常”。

修复后的默认行为：

- 使用当前本地 embedding 模型作为本次重建的规范模型，并以服务健康检查验证模型、维度和索引一致。
- 为每个索引保存构建元数据，并在启动和查询前验证兼容性。
- 将向量分数统一为“越高越相关”的相似度契约，不再混用 L2 距离与相似度。
- 默认只索引仍存在且状态为 `COMPLETED` 的文档，不自动把孤儿 chunk 恢复成可检索知识。
- 先执行 dry-run 并报告范围，再在临时目录构建，验证通过后备份旧索引并原子切换。
- 索引健康后再启动 consumer；待处理文档应进入明确状态，滞留消息应有可见的恢复手段。
- 管理端明确展示加载、空数据和错误状态，不把异常响应显示成“0 条”。

## User Stories

1. As a knowledge-base user, I want questions with relevant indexed content to return that content as the primary basis for the answer, so that the answer reflects the organization's knowledge rather than general model knowledge.
2. As a knowledge-base user, I want answers to include document and chunk citations when retrieval succeeds, so that I can verify the source.
3. As a knowledge-base user, I want to be told when no relevant content exists, so that I do not mistake a genuine no-match for a service failure.
4. As a knowledge-base user, I want an explicit unavailable state when retrieval cannot run, so that the system does not falsely claim the knowledge base has no relevant information.
5. As a knowledge-base user, I want the answer to stop using model fallback when the vector index is unhealthy, so that an infrastructure failure cannot produce a misleading answer.
6. As a knowledge-base user, I want questions in Chinese to retrieve semantically related Chinese chunks, so that the repair works for the actual language used by the product.
7. As a knowledge-base administrator, I want to see which documents are indexed, pending, failed, deleted, or excluded, so that I can understand what the chat can actually access.
8. As a knowledge-base administrator, I want a completed document to be considered searchable only after its chunks and vectors are both persisted, so that the UI does not claim readiness prematurely.
9. As a knowledge-base administrator, I want deleted or approval-blocked documents to remain excluded from retrieval, so that repair does not resurrect content that is not authorized.
10. As an operator, I want a preflight report showing the configured embedding model, index dimension, counts, and incompatible entries before rebuilding, so that I can approve a safe repair.
11. As an operator, I want the rebuild command to support a non-destructive dry-run, so that I can inspect its scope before changing the active vector index.
12. As an operator, I want a backup and atomic switch when applying a rebuilt index, so that a failed rebuild can be rolled back without losing the previous index.
13. As an operator, I want the rebuild to be idempotent, so that repeated runs do not create duplicate chunks or duplicate vectors.
14. As an operator, I want orphan chunks to be reported but excluded from the default rebuild, so that legacy or deleted documents are not silently exposed.
15. As an operator, I want a separate, explicit path for reviewing or re-uploading recoverable legacy knowledge, so that valuable content can be restored without weakening deletion guarantees.
16. As an operator, I want the vector store to stop converting dimension errors and backend failures into empty search results, so that health checks and logs expose the real failure.
17. As an operator, I want retrieval thresholds to have consistent semantics across FAISS and any future vector backend, so that changing a threshold has predictable behavior.
18. As an operator, I want exact and semantically related fixture queries to pass the production retrieval threshold, so that the threshold cannot again reject the best result.
19. As an operator, I want the Python consumer's availability and queue depth to be observable, so that a document waiting in RabbitMQ is not confused with a stalled database record.
20. As an operator, I want queued document messages to be processed only after the vector index is healthy, so that a repair cannot turn pending documents into failed documents.
21. As an operator, I want stale pending documents with no queued message to be identified and recoverable, so that they do not remain indefinitely pending.
22. As an administrator, I want the document list to distinguish load failure from an empty list, so that the “0 documents + loading” state is not shown after an API failure.
23. As an administrator, I want dashboard and user-management failures to show a retryable error state, so that I can distinguish a slow request from no data.
24. As a developer, I want regression tests to reproduce the model-dimension mismatch, score-direction bug, and empty-index behavior, so that the original failure cannot silently return.
25. As a developer, I want a high-level RAG API test using deterministic embeddings and a fake LLM, so that tests assert user-visible retrieval and citation behavior without network dependency.
26. As a maintainer, I want the index format to fail closed when metadata is missing or incompatible, so that an old index cannot be used with the wrong embedding model.
27. As a maintainer, I want an actionable health response for an incompatible or empty index, so that startup and operations reveal the repair requirement.
28. As a maintainer, I want repair behavior documented with rollback steps and recovery verification, so that another operator can safely repeat or undo it.

## Implementation Decisions

### Repair checklist

- [ ] Define an index manifest containing `schema_version`, `embedding_provider`, `embedding_model`, `embedding_dimension`, `built_at`, `document_count`, `chunk_count`, and the document eligibility policy.
- [ ] Validate the manifest and the actual vector dimension before serving retrieval; distinguish `INDEX_UNAVAILABLE` from `NO_RELEVANT_RESULT`.
- [ ] Stop swallowing retrieval backend errors as empty results; propagate a typed retrieval failure to the QA workflow and health endpoints.
- [ ] Adopt one score contract: higher values mean greater relevance, with a documented range and threshold direction.
- [ ] Use normalized embeddings and inner-product/cosine-style scoring for FAISS so its score contract matches the QA threshold semantics.
- [ ] Make the QA workflow return an explicit unavailable/error response when retrieval fails; reserve the “知识库没有找到相关内容” wording for a healthy search with no matches.
- [ ] Add a rebuild preflight that reports active-document chunks, orphan chunks, duplicate chunks, configured model, target dimension, and target location.
- [ ] Build a replacement index in a temporary location, validate it with fixture queries, then back up and atomically activate it.
- [ ] Make rebuild idempotent and deterministic for the same input snapshot and embedding model.
- [ ] Default the rebuild source to documents that still exist and are `COMPLETED`; never auto-adopt or auto-delete orphan chunks.
- [ ] Preserve a legacy-recovery report that lists orphan document identifiers and chunk counts for an explicit later decision.
- [ ] Add vector-index and document-consumer health signals to the operational surface.
- [ ] Recover the queued pending document only after index health passes.
- [ ] Detect stale `PENDING` documents that have no queued message and expose a safe requeue or re-upload path.
- [ ] Show loading, empty, and error as distinct frontend states for dashboard, user management, and document management.
- [ ] Keep the existing durable processing, retry, dead-letter, approval, and deletion guarantees unchanged.

### Index manifest

The active index must carry at least this metadata:

```text
schema_version
embedding_provider
embedding_model
embedding_dimension
score_metric
built_at
document_count
chunk_count
source_policy
```

The manifest is authoritative for compatibility checks. An index without a valid manifest is treated as incompatible until rebuilt or explicitly migrated.

### Retrieval contract

- All backends expose a similarity score where higher is more relevant.
- The QA workflow continues to express a minimum similarity threshold.
- FAISS uses normalized vectors and cosine-compatible scoring rather than interpreting raw L2 distance as similarity.
- A malformed index, dimension mismatch, or vector backend failure is a retrieval error, not an empty result.
- A healthy search that yields no candidates is the only path allowed to produce the normal no-match response.

### Rebuild behavior

- Dry-run is the default and produces a human-readable report plus a machine-readable manifest.
- Apply mode writes to a temporary sibling location and validates model loading, vector dimension, query retrieval, and expected counts before activation.
- The previous index is retained as a timestamped backup.
- Activation is atomic; any validation failure leaves the active index untouched.
- The default source policy is active `COMPLETED` documents only.
- Orphan chunks are excluded unless a later explicit migration decision changes their ownership and eligibility.
- Rebuild output must not contain duplicate vectors for one document/chunk identity.

### Consumer recovery

- Vector-index health must pass before document processing begins.
- Queue depth, consumer count, and processing attempts must be observable.
- A queued document with zero attempts is considered waiting for a consumer, not a parsing failure.
- A pending document with no queued or in-flight work is considered stale and requires an explicit recovery action.
- Reprocessing must retain the existing three-attempt, retry-queue, dead-letter, and idempotency behavior.

### Frontend behavior

- Pending requests show loading; successful empty responses show an empty state; failed requests show an actionable error and retry action.
- The document list must not initialize or present the confirmed count as zero while the request is still in flight.
- Index and consumer degradation should be visible to administrators without requiring terminal access.

## Testing Decisions

Good tests assert externally observable behavior: whether a known document is returned and cited, whether an unavailable index is reported as unavailable, and whether a rebuild leaves the prior index untouched when validation fails. Tests must not assert private logger text, internal loop structure, or exact implementation calls.

Selected test seams:

1. **RAG API integration seam.** Use a temporary vector index, deterministic embedding provider, and fake LLM to exercise the same API path used by chat. Assert relevant-source success, genuine no-match, and explicit index-unavailable behavior.
2. **Operator rebuild CLI seam.** Run the command as an operator with an explicit dry-run and apply flow. Assert scope reporting, idempotency, backup creation, atomic success, and rollback/no-op on validation failure.

These are the highest existing product seams that can reproduce the user-visible failure without requiring a real external embedding API or a real LLM response. If maintainers prefer a stricter one-seam design, the rebuild CLI test can produce an index that is immediately queried through the RAG API seam.

Prior art:

- Python document-processing tests use fake MySQL, parser, and vector-store dependencies.
- Approval-execution tests use fake persistence and vector components while asserting externally visible state transitions.
- Existing queue and document tests verify idempotency and bounded retry behavior, which the rebuild and recovery tests should mirror.

Required regression cases:

- A 1536-dimensional index with a 512-dimensional local embedding configuration fails loudly and does not return an empty successful result.
- A fixture query that exactly matches a chunk passes the production threshold and returns that chunk.
- A semantically related fixture query is not filtered out because a smaller distance was mistaken for a lower score.
- A genuinely unrelated query returns no sources and the normal no-match message.
- A healthy empty index returns the normal no-match response, while a missing or incompatible index returns an unavailable error.
- Two apply runs over the same source snapshot do not duplicate chunks or vectors.
- A failed validation does not replace or delete the active index.
- Active completed documents are indexed; deleted and approval-blocked documents are not.
- Orphan chunks appear in the dry-run report but are not indexed by default.
- A queued pending document is not processed until index health passes.
- A stale pending document is surfaced separately from a queued pending document.
- Admin pages render error state after a failed request instead of remaining in loading or showing a false zero.

## Out of Scope

- Switching the production embedding model to DashScope as the repair strategy.
- Automatically adopting, deleting, or reassigning orphan chunks.
- Deleting historical database rows or queue messages as part of the rebuild.
- Redesigning the chat experience or replacing the current LLM prompt.
- Changing document approval, deletion authorization, or audit semantics.
- Adding a new vector database or migrating to Milvus.
- General performance optimization unrelated to index validation, rebuild, or retrieval correctness.
- Fixing unrelated authentication, SMS, object-storage, report, or knowledge-inspection features.
- Rotating or changing external API credentials.

## Further Notes

Verified evidence from the current workspace:

- The active FAISS index has `d=1536`, `ntotal=4`, and contains only four `valid-document.txt` test vectors.
- The current runtime configuration uses the local `BAAI/bge-small-zh-v1.5` embedding model, whose query vector dimension is 512.
- A read-only reproduction returned `index.d=1536`, `query_dim=512`, `results=0`, and left the index hash unchanged.
- MySQL currently contains 17 document records, 755 chunks, and 737 chunks whose document record no longer exists.
- RabbitMQ currently reports one queued document-processing message and zero consumers; the corresponding document has zero processing attempts.
- A deterministic FAISS fixture showed an exact match at distance `0.0` and an unrelated document at `2.47`, confirming that the current lower-bound similarity threshold is reversed.
- The existing Java control-console logs for the slow admin-page interval were not persisted, so the exact cause of that delay needs browser request status and fresh backend logs before it is claimed as a Hikari or JVM stall.
- The specification was published as GitHub Issue #10 with the `ready-for-agent` label after GitHub CLI authentication was restored.
