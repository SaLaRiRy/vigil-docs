import pytest

from core.pending_recovery import (
    PendingRecoveryError,
    recover_pending_document,
)


class FakeMySQL:
    def __init__(self, row=None):
        self.row = row
        self.queries = []

    def fetch_one(self, sql, params=None, *, raise_on_error=False):
        self.queries.append((sql, params))
        return self.row


class FakePublisher:
    def __init__(self):
        self.published = []

    def publish(self, document_id, storage_path, attempt=1):
        self.published.append((document_id, storage_path, attempt))


def pending_row(status="PENDING", attempts=0):
    return {
        "id": 62,
        "file_path": "D:/uploads/defect.txt",
        "status": status,
        "attempts": attempts,
        "dead_lettered": 0,
    }


def test_dry_run_reports_stale_pending_document_without_publishing():
    publisher = FakePublisher()

    report = recover_pending_document(
        mysql=FakeMySQL(pending_row()),
        publisher=publisher,
        index_health={"status": "HEALTHY"},
        document_id=62,
        apply=False,
    )

    assert report["status"] == "would_requeue"
    assert report["document_id"] == 62
    assert report["attempts"] == 0
    assert publisher.published == []


def test_apply_requeues_the_explicit_pending_document_once():
    publisher = FakePublisher()

    report = recover_pending_document(
        mysql=FakeMySQL(pending_row()),
        publisher=publisher,
        index_health={"status": "EMPTY"},
        document_id=62,
        apply=True,
    )

    assert report["status"] == "requeued"
    assert publisher.published == [(62, "D:/uploads/defect.txt", 1)]


def test_recovery_refuses_unhealthy_index_before_touching_queue():
    publisher = FakePublisher()

    with pytest.raises(PendingRecoveryError, match="索引不可用"):
        recover_pending_document(
            mysql=FakeMySQL(pending_row()),
            publisher=publisher,
            index_health={"status": "UNAVAILABLE"},
            document_id=62,
            apply=True,
        )

    assert publisher.published == []


def test_recovery_refuses_documents_not_in_pending_state():
    with pytest.raises(PendingRecoveryError, match="PENDING"):
        recover_pending_document(
            mysql=FakeMySQL(pending_row(status="COMPLETED", attempts=1)),
            publisher=FakePublisher(),
            index_health={"status": "HEALTHY"},
            document_id=62,
            apply=True,
        )
