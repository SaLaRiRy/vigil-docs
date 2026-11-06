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


class StalePendingCounter:
    """Count pending documents that are old and have no processing progress."""

    def __init__(self, mysql, stale_after_minutes: int = 10):
        self.mysql = mysql
        self.stale_after_minutes = max(1, int(stale_after_minutes))

    def count(self) -> int:
        rows = self.mysql.fetch_all(
            """
            SELECT COUNT(*) AS stale_count
            FROM knowledge_doc d
            LEFT JOIN document_processing p ON p.doc_id = d.id
            WHERE d.status = 'PENDING'
              AND d.create_time < DATE_SUB(NOW(), INTERVAL %s MINUTE)
              AND COALESCE(p.attempts, 0) = 0
            """,
            (self.stale_after_minutes,),
            raise_on_error=True,
        )
        return int(rows[0]["stale_count"]) if rows else 0


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
    stale_pending_counter,
) -> Dict[str, Any]:
    vector_health = vector_store.get_health()
    index_status = vector_health.get("status", "UNAVAILABLE")
    try:
        queue_health = queue_inspector.inspect()
        queue_depth = int(queue_health.get("queueDepth", 0))
        consumer_count = int(queue_health.get("consumerCount", 0))
        stale_pending_count = int(stale_pending_counter.count())
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
                "stalePendingCount": 0,
                "message": f"无法获取 Consumer/队列状态: {exc}",
            },
        }

    return {
        "vectorIndex": vector_health,
        "documentConsumer": {
            "status": status,
            "queueDepth": queue_depth,
            "consumerCount": consumer_count,
            "stalePendingCount": stale_pending_count,
            "message": message,
        },
    }


def get_runtime_health(vector_store, mysql) -> Dict[str, Any]:
    return build_runtime_health(
        vector_store=vector_store,
        queue_inspector=RabbitQueueInspector(),
        stale_pending_counter=StalePendingCounter(mysql),
    )
