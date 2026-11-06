"""Explicitly requeue one stale pending document after index health passes."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import pika
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")
os.environ.setdefault("VECTOR_STORE_DISABLE_GLOBAL_INIT", "1")

from core.config import config
from core.mysql_client import mysql_client
from core.pending_recovery import recover_pending_document
from core.vector_store import VectorStoreManager, create_embeddings


class RabbitDocumentPublisher:
    def publish(self, document_id: int, storage_path: str, attempt: int = 1) -> None:
        credentials = pika.PlainCredentials(
            config.RABBITMQ_USERNAME,
            config.RABBITMQ_PASSWORD,
        )
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=config.RABBITMQ_HOST,
                port=config.RABBITMQ_PORT,
                credentials=credentials,
                heartbeat=10,
                socket_timeout=5,
                blocked_connection_timeout=5,
            )
        )
        try:
            channel = connection.channel()
            channel.confirm_delivery()
            message = {
                "schemaVersion": "1.0",
                "documentId": document_id,
                "storagePath": storage_path,
                "attempt": attempt,
                "enqueuedAt": datetime.now(timezone.utc).isoformat(),
            }
            channel.basic_publish(
                exchange="agentcraft.document.exchange",
                routing_key="document.process.v1",
                body=json.dumps(message, ensure_ascii=False).encode("utf-8"),
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=pika.DeliveryMode.Persistent,
                ),
                mandatory=True,
            )
        finally:
            if connection.is_open:
                connection.close()


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "恢复一个明确指定的滞留 PENDING 文档。默认只预览，不写队列。"
        )
    )
    parser.add_argument("--doc-id", type=int, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="确认后重新投递一条持久化文档处理消息",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    embeddings, provider, model = create_embeddings()
    manager = VectorStoreManager(
        use_milvus=False,
        embeddings=embeddings,
        reranker=None,
        embedding_provider=provider,
        embedding_model=model,
    )
    report = recover_pending_document(
        mysql=mysql_client,
        publisher=RabbitDocumentPublisher(),
        index_health=manager.get_health(),
        document_id=args.doc_id,
        apply=args.apply,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
