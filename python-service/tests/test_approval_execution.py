import json

import pytest

from core.approval_consumer import ApprovalDecisionHandler
from core.approval_execution import ApprovalExecutionError, ApprovalExecutionService


class FakeMySQL:
    def __init__(self, approval, document=None):
        self.approval = approval
        self.document = document or {
            "id": 7,
            "status": "WAITING_APPROVAL",
            "file_path": "missing-file.txt",
        }
        self.calls = []
        self.tool_calls = []
        self.audit_events = []

    def fetch_one(self, sql, params=None):
        if "FROM agent_approval" in sql:
            if (
                self.approval["id"] == params[0]
                and self.approval["run_id"] == params[1]
                and self.approval["document_id"] == params[2]
                and self.approval["tool_name"] == params[3]
            ):
                return dict(self.approval)
            return None
        if "FROM tool_call" in sql:
            return self.tool_calls[0] if self.tool_calls else None
        return None

    def get_document(self, doc_id):
        return self.document

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if sql.strip().startswith("UPDATE agent_approval") and "execution_status = 'EXECUTING'" in sql:
            return 1
        if sql.strip().startswith("UPDATE knowledge_doc"):
            previous = self.document["status"]
            self.document["status"] = "DELETED"
            return 0 if previous == "DELETED" else 1
        if sql.strip().startswith("INSERT INTO tool_call"):
            self.tool_calls.append({"id": "call-1"})
        return 1


class FakeVectorStore:
    def __init__(self):
        self.deleted = []

    def delete_document(self, doc_id):
        self.deleted.append(doc_id)


def approval(**overrides):
    value = {
        "id": "approval-1",
        "run_id": "run-1",
        "trace_id": "trace-1",
        "document_id": 7,
        "tool_name": "delete_document",
        "status": "APPROVED",
        "execution_status": "NOT_STARTED",
    }
    value.update(overrides)
    return value


def decision(decision_value="APPROVED"):
    return {
        "schemaVersion": "1.0",
        "approvalId": "approval-1",
        "runId": "run-1",
        "traceId": "trace-1",
        "documentId": 7,
        "decision": decision_value,
    }


def test_approval_bound_to_another_document_is_rejected():
    service = ApprovalExecutionService(FakeMySQL(approval()), FakeVectorStore())
    with pytest.raises(ApprovalExecutionError):
        service.validate_and_claim("approval-1", "run-1", 8)


def test_approved_deletion_soft_deletes_and_cleans_up():
    mysql = FakeMySQL(approval())
    vectors = FakeVectorStore()
    result = ApprovalExecutionService(mysql, vectors).execute(decision())

    assert result["status"] == "completed"
    assert mysql.document["status"] == "DELETED"
    assert vectors.deleted == [7]
    assert any("INSERT INTO tool_call" in sql for sql, _ in mysql.calls)


def test_rejection_never_invokes_deletion():
    mysql = FakeMySQL(approval())
    handler = ApprovalDecisionHandler(ApprovalExecutionService(mysql, FakeVectorStore()))

    assert handler.handle(json.dumps(decision("REJECTED")).encode()) == {"status": "rejected"}
    assert mysql.document["status"] == "WAITING_APPROVAL"
    assert not any("knowledge_doc" in sql for sql, _ in mysql.calls)


def test_completed_approval_replay_is_a_no_op():
    mysql = FakeMySQL(approval(execution_status="COMPLETED"))
    result = ApprovalExecutionService(mysql, FakeVectorStore()).execute(decision())

    assert result["status"] == "already_completed"
    assert not any("knowledge_doc" in sql for sql, _ in mysql.calls)


def test_already_deleted_document_is_a_safe_no_op():
    mysql = FakeMySQL(approval(), document={
        "id": 7,
        "status": "DELETED",
        "file_path": "missing-file.txt",
    })
    result = ApprovalExecutionService(mysql, FakeVectorStore()).execute(decision())

    assert result["alreadyDeleted"] is True
    assert result["status"] == "completed"
