from core.runtime_health import build_runtime_health, index_ready_for_consumption


class FakeVectorStore:
    def __init__(self, status):
        self.status = status

    def get_health(self):
        return {
            "status": self.status,
            "message": f"index is {self.status}",
            "dimension": 8,
            "expected_dimension": 8,
            "model": "fake-model",
        }


class FakeQueueInspector:
    def __init__(self, messages=0, consumers=1):
        self.messages = messages
        self.consumers = consumers

    def inspect(self):
        return {
            "queueDepth": self.messages,
            "consumerCount": self.consumers,
        }


class FakeStalePendingCounter:
    def __init__(self, count=0, document_ids=None):
        self.value = count
        self.document_ids = (
            list(document_ids)
            if document_ids is not None
            else list(range(1, self.value + 1))
        )

    def count(self):
        return self.value

    def list_ids(self):
        return list(self.document_ids)


def test_unavailable_index_blocks_consumption():
    assert index_ready_for_consumption(FakeVectorStore("UNAVAILABLE")) is False
    assert index_ready_for_consumption(FakeVectorStore("HEALTHY")) is True
    assert index_ready_for_consumption(FakeVectorStore("EMPTY")) is True


def test_queued_messages_without_consumers_are_degraded():
    health = build_runtime_health(
        vector_store=FakeVectorStore("HEALTHY"),
        queue_inspector=FakeQueueInspector(messages=1, consumers=0),
        stale_pending_counter=FakeStalePendingCounter(count=1),
    )

    assert health["vectorIndex"]["status"] == "HEALTHY"
    assert health["documentConsumer"] == {
        "status": "DEGRADED",
        "queueDepth": 1,
        "consumerCount": 0,
        "stalePendingCount": 1,
        "stalePendingDocumentIds": [1],
        "waitingForConsumer": True,
        "message": "有排队消息但 consumer 未运行",
    }


def test_running_consumer_with_empty_queue_is_healthy():
    health = build_runtime_health(
        vector_store=FakeVectorStore("EMPTY"),
        queue_inspector=FakeQueueInspector(messages=0, consumers=1),
        stale_pending_counter=FakeStalePendingCounter(count=0),
    )

    assert health["vectorIndex"]["status"] == "EMPTY"
    assert health["documentConsumer"]["status"] == "HEALTHY"


def test_stale_pending_document_ids_remain_visible():
    health = build_runtime_health(
        vector_store=FakeVectorStore("HEALTHY"),
        queue_inspector=FakeQueueInspector(messages=0, consumers=1),
        stale_pending_counter=FakeStalePendingCounter(
            count=1,
            document_ids=[47],
        ),
    )

    assert health["documentConsumer"]["stalePendingDocumentIds"] == [47]
