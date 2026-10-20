import pytest

from core.message_contract import MessageContractError, validate_document_message


def test_accepts_versioned_document_message():
    message = {
        "schemaVersion": "1.0",
        "documentId": 42,
        "storagePath": "D:/uploads/example.txt",
        "attempt": 1,
        "enqueuedAt": "2026-10-20T10:00:00+08:00",
    }

    assert validate_document_message(message) == message


@pytest.mark.parametrize(
    "message",
    [
        {"schemaVersion": "2.0", "documentId": 1, "storagePath": "a.txt"},
        {"schemaVersion": "1.0", "documentId": "1", "storagePath": "a.txt"},
        {"schemaVersion": "1.0", "documentId": 1, "storagePath": ""},
    ],
)
def test_rejects_unsupported_or_incomplete_document_messages(message):
    with pytest.raises(MessageContractError):
        validate_document_message(message)
