from types import SimpleNamespace

import pytest

from core.document_processor import DocumentProcessor, ProcessingAttemptFailed


class FakeChunk:
    def __init__(self, content):
        self.page_content = content
        self.metadata = {}


class FakeParser:
    def __init__(self, chunks=None, error=None):
        self.chunks = chunks or []
        self.error = error

    def parse(self, storage_path):
        if self.error:
            raise self.error
        return self.chunks


class FakeMySQL:
    def __init__(self, document=None, attempts=1):
        self.document = document or {"status": "PENDING"}
        self.attempts = attempts
        self.failed = None
        self.retry_pending = None
        self.completed_chunks = None

    def get_document(self, doc_id):
        return self.document

    def increment_processing_attempt(self, doc_id):
        return self.attempts

    def mark_processing(self, doc_id):
        self.document["status"] = "PROCESSING"

    def complete_document(self, doc_id, chunks):
        self.completed_chunks = chunks

    def mark_failed(self, doc_id, safe_error, dead_lettered):
        self.failed = (safe_error, dead_lettered)

    def mark_retry_pending(self, doc_id, safe_error):
        self.retry_pending = safe_error


class FakeVectorStore:
    def __init__(self):
        self.deleted = []
        self.added = []

    def delete_document(self, doc_id):
        self.deleted.append(doc_id)

    def add_documents(self, chunks):
        self.added.extend(chunks)


def document_message(doc_id=7, attempt=1):
    return {
        "schemaVersion": "1.0",
        "documentId": doc_id,
        "storagePath": "D:/uploads/example.txt",
        "attempt": attempt,
    }


def test_redelivery_replaces_vectors_and_chunks_for_same_document():
    mysql = FakeMySQL()
    vectors = FakeVectorStore()
    processor = DocumentProcessor(
        FakeParser([FakeChunk("first"), FakeChunk("second")]),
        mysql,
        vectors,
    )

    assert processor.process(document_message()) == "completed"
    assert vectors.deleted == [7]
    assert [chunk.page_content for chunk in vectors.added] == ["first", "second"]
    assert [chunk["chunk_index"] for chunk in mysql.completed_chunks] == [0, 1]


def test_third_failure_is_reported_as_final_and_dead_lettered():
    mysql = FakeMySQL(attempts=3)
    processor = DocumentProcessor(
        FakeParser(error=ValueError("broken document")),
        mysql,
        FakeVectorStore(),
        max_attempts=3,
    )

    with pytest.raises(ProcessingAttemptFailed) as raised:
        processor.process(document_message())

    assert raised.value.final is True
    assert mysql.failed == ("Document could not be parsed or indexed", True)


def test_first_failure_is_retryable():
    mysql = FakeMySQL(attempts=1)
    processor = DocumentProcessor(
        FakeParser(error=ValueError("temporary failure")),
        mysql,
        FakeVectorStore(),
        max_attempts=3,
    )

    with pytest.raises(ProcessingAttemptFailed) as raised:
        processor.process(document_message())

    assert raised.value.final is False
    assert mysql.retry_pending == "Document could not be parsed or indexed"
    assert mysql.failed is None


def test_deleted_document_is_an_idempotent_no_op():
    processor = DocumentProcessor(
        FakeParser(error=AssertionError("must not parse")),
        FakeMySQL({"status": "DELETED"}),
        FakeVectorStore(),
    )

    assert processor.process(document_message()) == "already_deleted"
