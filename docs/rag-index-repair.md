# RAG 索引检查与安全重建

对应工单：[Issue #10](https://github.com/SaLaRiRy/vigil-docs/issues/10)

## 默认行为

- 只重建仍存在且状态为 `COMPLETED` 的文档。
- 孤儿 chunk 只出现在报告中，不自动恢复、不自动删除。
- 缺少 manifest、模型不匹配或维度不匹配的索引会被标记为 `UNAVAILABLE`，不会返回伪空结果。
- 重建命令默认是 dry-run；只有显式传入 `--apply` 才会修改活动索引目录。
- Apply 模式先构建临时索引并验证，再把旧索引移动为时间戳备份，最后激活新索引。

## 1. Dry-run

在 `python-service` 目录运行：

```powershell
$env:HF_HUB_OFFLINE='1'
.\.venv\Scripts\python.exe .\rebuild_index.py
```

报告中需要检查：

- `embedding_provider` 和 `embedding_model` 是否与运行时配置一致。
- `embedding_dimension` 是否符合预期。
- `active_document_count`、`active_chunk_count` 是否是本次要恢复的范围。
- `orphan_documents` 是否与已知历史数据一致。
- `duplicate_chunk_indexes` 是否只是历史解析数据；重复内容会按文档和正文哈希去重。

Dry-run 不创建、不移动、不覆盖活动索引。

## 2. 构建并激活

确认 dry-run 范围后运行：

```powershell
$env:HF_HUB_OFFLINE='1'
.\.venv\Scripts\python.exe .\rebuild_index.py --apply
```

成功时报告包含：

- `status: activated`
- `built_chunk_count`
- `backup_directory`

旧索引会保留在 `faiss_index.backup-<时间戳>-<随机后缀>`，不会被删除。

## 3. 验证

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/runtime-health
```

期望结果：

- `vectorIndex.status` 为 `HEALTHY` 或 `EMPTY`。
- 文档 consumer 运行时，`documentConsumer.consumerCount` 大于 0。
- 查询命中时返回文档引用；没有命中时返回正常 no-match；索引故障时返回 `INDEX_UNAVAILABLE`。

## 4. 回滚

如新索引验证失败，但临时构建阶段的自动回滚没有发生，可以手动恢复：

1. 停止 Python API 和 consumer。
2. 把当前 `faiss_index` 移到另一个保留目录，例如 `faiss_index.failed-<时间戳>`。
3. 把最近的 `faiss_index.backup-*` 重命名回 `faiss_index`。
4. 重新启动服务并检查 `/api/health`。

不要在回滚过程中删除旧备份；保留它直到问题定位完成。

## 5. Pending 文档恢复

- consumer 在向量索引 `HEALTHY` 或 `EMPTY` 前不会消费消息。
- 有排队消息但 `consumerCount=0` 时，健康接口会报告 `DEGRADED`。
- 长时间无 processing attempt 的 `PENDING` 文档会在 `stalePendingCount` 中显示。
- 这些恢复动作不会自动修改数据库或队列；需要由管理员显式重投或重新上传。
