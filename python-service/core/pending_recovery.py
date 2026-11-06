from typing import Any, Dict


READY_INDEX_STATUSES = {"HEALTHY", "EMPTY"}


class PendingRecoveryError(RuntimeError):
    pass


def recover_pending_document(
    *,
    mysql,
    publisher,
    index_health: Dict[str, Any],
    document_id: int,
    apply: bool = False,
) -> Dict[str, Any]:
    """Inspect or explicitly requeue one stale pending document."""
    if not isinstance(document_id, int) or document_id <= 0:
        raise PendingRecoveryError("document_id 必须是正整数")
    if index_health.get("status") not in READY_INDEX_STATUSES:
        raise PendingRecoveryError("向量索引不可用，不能安全地重新投递文档")

    row = mysql.fetch_one(
        """
        SELECT d.id, d.file_path, d.status,
               COALESCE(p.attempts, 0) AS attempts,
               COALESCE(p.dead_lettered, 0) AS dead_lettered
        FROM knowledge_doc d
        LEFT JOIN document_processing p ON p.doc_id = d.id
        WHERE d.id = %s
        """,
        (document_id,),
        raise_on_error=True,
    )
    if not row:
        raise PendingRecoveryError(f"文档 {document_id} 不存在")
    if row["status"] != "PENDING":
        raise PendingRecoveryError(
            f"文档 {document_id} 当前状态为 {row['status']}，只有 PENDING 可重新投递"
        )
    if not row.get("file_path"):
        raise PendingRecoveryError(f"文档 {document_id} 缺少原始文件路径")

    report = {
        "document_id": int(row["id"]),
        "storage_path": row["file_path"],
        "attempts": int(row.get("attempts") or 0),
        "dead_lettered": bool(row.get("dead_lettered")),
        "source_policy": "explicit_pending_only",
        "status": "requeued" if apply else "would_requeue",
    }
    if apply:
        publisher.publish(
            report["document_id"],
            report["storage_path"],
            attempt=1,
        )
    return report
