import json
import logging
import time
from typing import Any, Dict

import pika

from core.approval_consumer import ApprovalDecisionHandler
from core.approval_execution import ApprovalExecutionService
from core.config import config
from core.document_processor import DocumentProcessor, ProcessingAttemptFailed
from core.message_contract import MessageContractError, validate_document_message
from core.mysql_client import mysql_client
from core.parser import DocumentParser
from core.vector_store import vector_store
from tools.delete_document import DeleteDocumentTool
from tools.registry import tool_registry


EXCHANGE = "agentcraft.document.exchange"
ROUTING_KEY = "document.process.v1"
RETRY_ROUTING_KEY = "document.retry.v1"
DEAD_ROUTING_KEY = "document.dead.v1"


def declare_topology(channel) -> None:
    channel.exchange_declare(exchange=EXCHANGE, exchange_type="direct", durable=True)
    channel.queue_declare(queue=config.DOCUMENT_QUEUE, durable=True)
    channel.queue_bind(queue=config.DOCUMENT_QUEUE, exchange=EXCHANGE, routing_key=ROUTING_KEY)
    channel.queue_declare(
        queue=config.DOCUMENT_RETRY_QUEUE,
        durable=True,
        arguments={
            "x-message-ttl": 1500,
            "x-dead-letter-exchange": EXCHANGE,
            "x-dead-letter-routing-key": ROUTING_KEY,
        },
    )
    channel.queue_bind(
        queue=config.DOCUMENT_RETRY_QUEUE,
        exchange=EXCHANGE,
        routing_key=RETRY_ROUTING_KEY,
    )
    channel.queue_declare(queue=config.DOCUMENT_DLQ, durable=True)
    channel.queue_bind(queue=config.DOCUMENT_DLQ, exchange=EXCHANGE, routing_key=DEAD_ROUTING_KEY)

    approval_exchange = "agentcraft.approval.exchange"
    channel.exchange_declare(exchange=approval_exchange, exchange_type="direct", durable=True)
    channel.queue_declare(queue=config.APPROVAL_DECISION_QUEUE, durable=True)
    channel.queue_bind(
        queue=config.APPROVAL_DECISION_QUEUE,
        exchange=approval_exchange,
        routing_key="approval.decision.v1",
    )


def publish_json(channel, routing_key: str, payload: Dict[str, Any]) -> None:
    channel.basic_publish(
        exchange=EXCHANGE,
        routing_key=routing_key,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=pika.DeliveryMode.Persistent,
        ),
    )


def handle_document_message(
    channel,
    body: bytes,
    processor: DocumentProcessor,
) -> None:
    try:
        raw = json.loads(body.decode("utf-8"))
        validate_document_message(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, MessageContractError):
        logging.exception("Rejecting malformed document message")
        publish_json(channel, DEAD_ROUTING_KEY, {"reason": "invalid_document_message"})
        return

    try:
        processor.process(raw)
    except ProcessingAttemptFailed as exc:
        payload = dict(raw)
        payload["attempt"] = exc.attempt + 1
        if exc.final:
            publish_json(channel, DEAD_ROUTING_KEY, payload)
        else:
            publish_json(channel, RETRY_ROUTING_KEY, payload)


def make_connection() -> pika.BlockingConnection:
    credentials = pika.PlainCredentials(config.RABBITMQ_USERNAME, config.RABBITMQ_PASSWORD)
    return pika.BlockingConnection(
        pika.ConnectionParameters(
            host=config.RABBITMQ_HOST,
            port=config.RABBITMQ_PORT,
            credentials=credentials,
            heartbeat=30,
        )
    )


def main() -> None:
    while True:
        try:
            connection = make_connection()
            channel = connection.channel()
            channel.basic_qos(prefetch_count=1)
            declare_topology(channel)
            processor = DocumentProcessor(DocumentParser(), mysql_client, vector_store)
            approval_executor = ApprovalExecutionService(mysql_client, vector_store)
            tool_registry.register_tool(DeleteDocumentTool(approval_executor))
            approval_handler = ApprovalDecisionHandler(approval_executor, tool_registry)

            def callback(ch, method, properties, message_body):
                try:
                    handle_document_message(ch, message_body, processor)
                finally:
                    # Status is terminal, or the retry/dead-letter message has
                    # been durably accepted before the original delivery is acked.
                    ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_consume(queue=config.DOCUMENT_QUEUE, on_message_callback=callback)
            def approval_callback(ch, method, properties, message_body):
                try:
                    approval_handler.handle(message_body)
                finally:
                    ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_consume(
                queue=config.APPROVAL_DECISION_QUEUE,
                on_message_callback=approval_callback,
            )
            logging.info("Document consumer listening on %s", config.DOCUMENT_QUEUE)
            channel.start_consuming()
        except KeyboardInterrupt:
            break
        except Exception:
            logging.exception("Document consumer disconnected; retrying")
            time.sleep(3)


if __name__ == "__main__":
    main()
