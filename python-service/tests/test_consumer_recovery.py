from core.runtime_health import build_runtime_health


class BrokenVectorStore:
    def get_health(self):
        raise RuntimeError("index inspection failed")


class HealthyVectorStore:
    def get_health(self):
        return {"status": "HEALTHY", "message": "index is healthy"}


class FakeQueueInspector:
    def inspect(self):
        return {"queueDepth": 1, "consumerCount": 0}


class FakeWorkCounter:
    def snapshot(self):
        return {
            "pendingCount": 2,
            "processingCount": 0,
            "stalePendingCount": 2,
            "maxProcessingAttempts": 0,
        }

    def list_ids(self):
        return [47, 48]


class FakeProcessor:
    def __init__(self):
        self.messages = []

    def process(self, message):
        self.messages.append(message)


class FakeChannel:
    def __init__(self):
        self.acks = []
        self.nacks = []
        self.stop_count = 0

    def basic_ack(self, delivery_tag):
        self.acks.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue):
        self.nacks.append((delivery_tag, requeue))

    def stop_consuming(self):
        self.stop_count += 1


def test_runtime_health_reports_broken_vector_inspection():
    health = build_runtime_health(
        vector_store=BrokenVectorStore(),
        queue_inspector=FakeQueueInspector(),
        work_counter=FakeWorkCounter(),
    )

    assert health["vectorIndex"]["status"] == "UNAVAILABLE"
    assert health["documentConsumer"]["status"] == "UNAVAILABLE"
    assert health["documentConsumer"]["stalePendingCount"] == 2


def test_unavailable_index_requeues_delivery_without_processing():
    from consumer import process_document_delivery

    channel = FakeChannel()
    processor = FakeProcessor()
    body = (
        b'{"schemaVersion":"1.0","documentId":62,'
        b'"storagePath":"D:/uploads/doc.txt","attempt":1,'
        b'"enqueuedAt":"2026-11-07T00:00:00+08:00"}'
    )

    consumed = process_document_delivery(
        channel=channel,
        delivery_tag=17,
        body=body,
        processor=processor,
        vector_store=BrokenVectorStore(),
    )

    assert consumed is False
    assert processor.messages == []
    assert channel.acks == []
    assert channel.nacks == [(17, True)]
    assert channel.stop_count == 1


def test_healthy_index_accepts_delivery_after_processing():
    from consumer import process_document_delivery

    channel = FakeChannel()
    processor = FakeProcessor()
    body = (
        b'{"schemaVersion":"1.0","documentId":62,'
        b'"storagePath":"D:/uploads/doc.txt","attempt":1,'
        b'"enqueuedAt":"2026-11-07T00:00:00+08:00"}'
    )

    consumed = process_document_delivery(
        channel=channel,
        delivery_tag=18,
        body=body,
        processor=processor,
        vector_store=HealthyVectorStore(),
    )

    assert consumed is True
    assert processor.messages[0]["documentId"] == 62
    assert channel.acks == [18]
    assert channel.nacks == []
