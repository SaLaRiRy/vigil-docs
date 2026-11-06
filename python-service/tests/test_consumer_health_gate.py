import os

os.environ.setdefault("VECTOR_STORE_DISABLE_GLOBAL_INIT", "1")

from consumer import process_document_delivery


class UnavailableIndex:
    def get_health(self):
        return {"status": "UNAVAILABLE", "message": "索引维度不匹配"}


class RecordingChannel:
    def __init__(self):
        self.acknowledged = []
        self.requeued = []

    def basic_ack(self, delivery_tag):
        self.acknowledged.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue):
        self.requeued.append((delivery_tag, requeue))


class RecordingProcessor:
    def __init__(self):
        self.calls = 0

    def process(self, message):
        self.calls += 1


def test_unavailable_index_requeues_without_processing_the_document():
    channel = RecordingChannel()
    processor = RecordingProcessor()

    accepted = process_document_delivery(
        channel=channel,
        delivery_tag=17,
        body=b'{"docId": 62}',
        processor=processor,
        vector_store=UnavailableIndex(),
    )

    assert accepted is False
    assert processor.calls == 0
    assert channel.acknowledged == []
    assert channel.requeued == [(17, True)]
