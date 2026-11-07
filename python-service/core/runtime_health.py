from typing import Any, Dict

import pika

from core.config import config


READY_INDEX_STATUSES = {"HEALTHY", "EMPTY"}


def index_ready_for_consumption(vector_store) -> bool:
    try:
        return vector_store.get_health().get("status") in READY_INDEX_STATUSES
    except Exception:
        config.logger.exception("Unable to determine vector index health")
        return False


class RabbitQueueInspector:
    """Read queue metadata without consuming, acknowledging, or rejecting messages."""

    def __init__(self, queue: str = None):
        self.queue = queue or config.DOCUMENT_QUEUE

    def inspect(self) -> Dict[str, int]:
        credentials = pika.PlainCredentials(
            config.RABBITMQ_USERNAME,
            config.RABBITMQ_PASSWORD,
        )
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=config.RABBITMQ_HOST,
                port=config.RABBITMQ_PORT,
                credentials=credentials,
                heartbeat=5,
                socket_timeout=3,
                blocked_connection_timeout=3,
            )
        )
        try:
            channel = connection.channel()
            result = channel.queue_declare(
                queue=self.queue,
                durable=True,
                passive=True,
            )
            return {
                "queueDepth": int(result.method.message_count),
                "consumerCount": int(result.method.consumer_count),
            }
        finally:
            if connection.is_open:
                connection.close()


class DocumentWorkCounter:
    """Summarize document work without changing queue or database state."""

    def __init__(self, mysql, stale_after_minutes: int = 10):
        self.mysql = mysql
        self.stale_after_minutes = max(1, int(stale_after_minutes))

    def snapshot(self) -> Dict[str, int]:
        rows = self.mysql.fetch_all(
            """
            SELECT
                SUM(CASE WHEN d.status = 'PENDING' THEN 1 ELSE 0 END)
                    AS pending_count,
                SUM(CASE WHEN d.status = 'PROCESSING' THEN 1 ELSE 0 END)
                    AS processing_count,
                SUM(
                    CASE
                        WHEN d.status = 'PENDING'
                         AND d.create_time < DATE_SUB(NOW(), INTERVAL %s MINUTE)
                         AND COALESCE(p.attempts, 0) = 0
                        THEN 1
                        ELSE 0
                    END
                ) AS stale_pending_count,
                COALESCE(MAX(p.attempts), 0) AS max_processing_attempts
            FROM knowledge_doc d
            LEFT JOIN document_processing p ON p.doc_id = d.id
            """,
            (self.stale_after_minutes,),
            raise_on_error=True,
        )
        row = rows[0] if rows else {}
        return {
            "pendingCount": int(row.get("pending_count") or 0),
            "processingCount": int(row.get("processing_count") or 0),
            "stalePendingCount": int(row.get("stale_pending_count") or 0),
            "maxProcessingAttempts": int(
                row.get("max_processing_attempts") or 0
            ),
        }

    def list_ids(self) -> list[int]:
        rows = self.mysql.fetch_all(
            """
            SELECT d.id
            FROM knowledge_doc d
            LEFT JOIN document_processing p ON p.doc_id = d.id
            WHERE d.status = 'PENDING'
              AND d.create_time < DATE_SUB(NOW(), INTERVAL %s MINUTE)
              AND COALESCE(p.attempts, 0) = 0
            ORDER BY d.id
            """,
            (self.stale_after_minutes,),
            raise_on_error=True,
        )
        return [int(row["id"]) for row in rows]

    def list_completed_document_ids(self) -> list[int]:
        rows = self.mysql.fetch_all(
            """
            SELECT id
            FROM knowledge_doc
            WHERE status = 'COMPLETED'
            ORDER BY id
            """,
            raise_on_error=True,
        )
        return [int(row["id"]) for row in rows]


def _consumer_status(
    *,
    index_status: str,
    queue_depth: int,
    consumer_count: int,
) -> tuple[str, str]:
    if index_status not in READY_INDEX_STATUSES:
        return "UNAVAILABLE", "向量索引未就绪，consumer 已暂停"
    if queue_depth > 0 and consumer_count == 0:
        return "DEGRADED", "有排队消息但 consumer 未运行"
    if consumer_count == 0:
        return "DEGRADED", "consumer 未运行"
    return "HEALTHY", "consumer 正在运行"


def build_runtime_health(
    *,
    vector_store,
    queue_inspector,
    work_counter,
) -> Dict[str, Any]:
    try:
        vector_health = vector_store.get_health()
    except Exception as exc:
        config.logger.exception("Unable to inspect vector index health")
        vector_health = {
            "status": "UNAVAILABLE",
            "message": f"无法检查向量索引状态: {exc}",
        }
    vector_health = dict(vector_health)
    index_status = vector_health.get("status", "UNAVAILABLE")

    stale_pending_document_ids = []
    try:
        work_snapshot = work_counter.snapshot()
        stale_pending_document_ids = list(work_counter.list_ids())
        completed_document_ids = set(work_counter.list_completed_document_ids())
        indexed_document_ids = {
            int(doc_id) for doc_id in vector_health.get("indexedDocumentIds", [])
        }
        missing_document_ids = sorted(completed_document_ids - indexed_document_ids)
        if missing_document_ids and index_status in READY_INDEX_STATUSES:
            vector_health["status"] = "DEGRADED"
            vector_health["message"] = (
                "索引缺少已完成的文档: "
                + ", ".join(str(doc_id) for doc_id in missing_document_ids)
            )
            vector_health["missingDocumentIds"] = missing_document_ids
    except Exception as exc:
        config.logger.warning("Unable to inspect pending document work: %s", exc)
        work_snapshot = {
            "pendingCount": 0,
            "processingCount": 0,
            "stalePendingCount": 0,
            "maxProcessingAttempts": 0,
        }

    try:
        queue_health = queue_inspector.inspect()
        queue_depth = int(queue_health.get("queueDepth", 0))
        consumer_count = int(queue_health.get("consumerCount", 0))
        status, message = _consumer_status(
            index_status=index_status,
            queue_depth=queue_depth,
            consumer_count=consumer_count,
        )
    except Exception as exc:
        config.logger.warning("Runtime consumer health check failed: %s", exc)
        return {
            "vectorIndex": vector_health,
            "documentConsumer": {
                "status": "UNAVAILABLE",
                "queueDepth": 0,
                "consumerCount": 0,
                **work_snapshot,
                "stalePendingDocumentIds": stale_pending_document_ids,
                "waitingForConsumer": False,
                "message": f"无法获取 Consumer/队列状态: {exc}",
            },
        }

    return {
        "vectorIndex": vector_health,
        "documentConsumer": {
            "status": status,
            "queueDepth": queue_depth,
            "consumerCount": consumer_count,
            **work_snapshot,
            "stalePendingDocumentIds": stale_pending_document_ids,
            "waitingForConsumer": queue_depth > 0 and consumer_count == 0,
            "message": message,
        },
    }


def get_runtime_health(vector_store, mysql) -> Dict[str, Any]:
    return build_runtime_health(
        vector_store=vector_store,
        queue_inspector=RabbitQueueInspector(),
        work_counter=DocumentWorkCounter(mysql),
    )
