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


class FakeDocumentWorkCounter:
    def __init__(
        self,
        pending=0,
        processing=0,
        stale=0,
        max_attempts=0,
        stale_document_ids=None,
        completed_document_ids=None,
    ):
        self.stale_document_ids = (
            list(stale_document_ids) if stale_document_ids is not None else []
        )
        self.values = {
            "pendingCount": pending,
            "processingCount": processing,
            "stalePendingCount": stale,
            "maxProcessingAttempts": max_attempts,
        }
        self.completed_document_ids = (
            list(completed_document_ids)
            if completed_document_ids is not None
            else []
        )

    def snapshot(self):
        return dict(self.values)

    def list_ids(self):
        return list(self.stale_document_ids)

    def list_completed_document_ids(self):
        return list(self.completed_document_ids)


def test_unavailable_index_blocks_consumption():
    assert index_ready_for_consumption(FakeVectorStore("UNAVAILABLE")) is False
    assert index_ready_for_consumption(FakeVectorStore("HEALTHY")) is True
    assert index_ready_for_consumption(FakeVectorStore("EMPTY")) is True


def test_queued_messages_without_consumers_are_degraded():
    health = build_runtime_health(
        vector_store=FakeVectorStore("HEALTHY"),
        queue_inspector=FakeQueueInspector(messages=1, consumers=0),
        work_counter=FakeDocumentWorkCounter(
            pending=1,
            stale=1,
            max_attempts=0,
            stale_document_ids=[1],
        ),
    )

    assert health["vectorIndex"]["status"] == "HEALTHY"
    assert health["documentConsumer"] == {
        "status": "DEGRADED",
        "queueDepth": 1,
        "consumerCount": 0,
        "pendingCount": 1,
        "processingCount": 0,
        "stalePendingCount": 1,
        "maxProcessingAttempts": 0,
        "stalePendingDocumentIds": [1],
        "waitingForConsumer": True,
        "message": "有排队消息但 consumer 未运行",
    }


def test_running_consumer_with_empty_queue_is_healthy():
    health = build_runtime_health(
        vector_store=FakeVectorStore("EMPTY"),
        queue_inspector=FakeQueueInspector(messages=0, consumers=1),
        work_counter=FakeDocumentWorkCounter(),
    )

    assert health["vectorIndex"]["status"] == "EMPTY"
    assert health["documentConsumer"]["status"] == "HEALTHY"


def test_stale_pending_document_ids_remain_visible():
    health = build_runtime_health(
        vector_store=FakeVectorStore("HEALTHY"),
        queue_inspector=FakeQueueInspector(messages=0, consumers=1),
        work_counter=FakeDocumentWorkCounter(
            stale=1,
            stale_document_ids=[47],
        ),
    )

    assert health["documentConsumer"]["stalePendingDocumentIds"] == [47]


def test_completed_document_missing_from_index_is_degraded():
    vector_store = FakeVectorStore("HEALTHY")
    vector_store.get_health = lambda: {
        "status": "HEALTHY",
        "message": "向量索引可检索",
        "indexedDocumentIds": [46],
    }
    health = build_runtime_health(
        vector_store=vector_store,
        queue_inspector=FakeQueueInspector(messages=0, consumers=1),
        work_counter=FakeDocumentWorkCounter(
            completed_document_ids=[46, 65],
        ),
    )

    assert health["vectorIndex"]["status"] == "DEGRADED"
    assert health["vectorIndex"]["missingDocumentIds"] == [65]
    assert health["documentConsumer"]["status"] == "HEALTHY"
