from datetime import datetime
from typing import Any, Dict


DOCUMENT_SCHEMA_VERSION = "1.0"


class MessageContractError(ValueError):
    pass


def validate_document_message(message: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(message, dict):
        raise MessageContractError("Document message must be an object")
    if message.get("schemaVersion") != DOCUMENT_SCHEMA_VERSION:
        raise MessageContractError("Unsupported document message schema version")

    document_id = message.get("documentId")
    if not isinstance(document_id, int) or document_id <= 0:
        raise MessageContractError("documentId must be a positive integer")

    storage_path = message.get("storagePath")
    if not isinstance(storage_path, str) or not storage_path.strip():
        raise MessageContractError("storagePath is required")

    attempt = message.get("attempt", 1)
    if not isinstance(attempt, int) or attempt < 1:
        raise MessageContractError("attempt must be a positive integer")

    enqueued_at = message.get("enqueuedAt")
    if enqueued_at is not None:
        try:
            datetime.fromisoformat(str(enqueued_at).replace("Z", "+00:00"))
        except ValueError as exc:
            raise MessageContractError("enqueuedAt must be ISO-8601") from exc

    return message


def validate_approval_decision(message: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(message, dict):
        raise MessageContractError("Approval decision message must be an object")
    if message.get("schemaVersion") != "1.0":
        raise MessageContractError("Unsupported approval decision schema version")
    for field in ("approvalId", "runId", "documentId", "decision"):
        if field not in message:
            raise MessageContractError(f"{field} is required")
    if message["decision"] not in ("APPROVED", "REJECTED"):
        raise MessageContractError("decision must be APPROVED or REJECTED")
    if not isinstance(message["documentId"], int) or message["documentId"] <= 0:
        raise MessageContractError("documentId must be a positive integer")
    return message
