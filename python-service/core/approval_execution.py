import json
import os
from typing import Any, Dict, Optional


class ApprovalExecutionError(RuntimeError):
    pass


class ApprovalExecutionService:
    def __init__(self, mysql, vector_store):
        self.mysql = mysql
        self.vector_store = vector_store

    def validate_and_claim(
        self,
        approval_id: str,
        run_id: str,
        document_id: int,
        tool_name: str = "delete_document",
    ) -> Dict[str, Any]:
        approval = self.mysql.fetch_one(
            """
            SELECT * FROM agent_approval
            WHERE id = %s AND run_id = %s AND document_id = %s AND tool_name = %s
            """,
            (approval_id, run_id, document_id, tool_name),
        )
        if not approval:
            raise ApprovalExecutionError("Approval ticket is not bound to this run and document")
        if approval["status"] != "APPROVED":
            raise ApprovalExecutionError("Approval ticket is not approved")
        if approval["execution_status"] == "COMPLETED":
            return approval
        if approval["execution_status"] == "EXECUTING":
            # A redelivery or a process restart may resume an already claimed
            # ticket. Soft deletion and cleanup remain idempotent.
            return approval

        claimed = self.mysql.execute(
            """
            UPDATE agent_approval
            SET execution_status = 'EXECUTING'
            WHERE id = %s AND run_id = %s AND document_id = %s
              AND tool_name = %s AND status = 'APPROVED'
              AND execution_status IN ('NOT_STARTED', 'EXECUTING')
            """,
            (approval_id, run_id, document_id, tool_name),
        )
        if claimed != 1:
            latest = self.mysql.fetch_one("SELECT * FROM agent_approval WHERE id = %s", (approval_id,))
            if latest and latest["execution_status"] == "COMPLETED":
                return latest
            raise ApprovalExecutionError("Approval ticket could not be claimed")
        return approval

    def execute(self, message: Dict[str, Any]) -> Dict[str, Any]:
        approval_id = message["approvalId"]
        run_id = message["runId"]
        document_id = int(message["documentId"])
        approval = self.validate_and_claim(approval_id, run_id, document_id)

        if approval["execution_status"] == "COMPLETED":
            return {"status": "already_completed", "documentId": document_id}

        document = self.mysql.get_document(document_id)
        if not document:
            self._complete(approval_id, run_id)
            return {"status": "document_missing", "documentId": document_id}

        soft_deleted = self.mysql.execute(
            "UPDATE knowledge_doc SET status = 'DELETED' WHERE id = %s AND status <> 'DELETED'",
            (document_id,),
        )
        already_deleted = soft_deleted == 0

        existing_call = self.mysql.fetch_one(
            "SELECT id FROM tool_call WHERE run_id = %s AND tool_name = 'delete_document' LIMIT 1",
            (run_id,),
        )
        if not existing_call:
            self.mysql.execute(
                """
                INSERT INTO tool_call
                    (id, tool_call_id, run_id, tool_name, input_params, output, status,
                     duration_ms, error_message, timestamp, created_at)
                VALUES
                    (UUID(), UUID(), %s, 'delete_document', %s, %s, 'success',
                     0, NULL, NOW(), NOW())
                """,
                (
                    run_id,
                    json.dumps({"documentId": document_id, "approvalId": approval_id}),
                    json.dumps({"status": "deleted", "alreadyDeleted": already_deleted}),
                ),
            )

        self.mysql.execute(
            """
            UPDATE agent_run
            SET status = 'completed', end_time = NOW(),
                output = 'Approved document deletion completed'
            WHERE run_id = %s
            """,
            (run_id,),
        )
        self.mysql.execute(
            "UPDATE agent_approval SET cleanup_status = 'PENDING' WHERE id = %s",
            (approval_id,),
        )
        self.audit(run_id, approval["trace_id"], "DOCUMENT_SOFT_DELETED", {
            "approvalId": approval_id,
            "documentId": document_id,
            "alreadyDeleted": already_deleted,
        })

        cleanup_error: Optional[str] = None
        try:
            self._cleanup(document_id, document.get("file_path"))
            self.mysql.execute(
                "UPDATE agent_approval SET cleanup_status = 'COMPLETED' WHERE id = %s",
                (approval_id,),
            )
            self.audit(run_id, approval["trace_id"], "CLEANUP_COMPLETED", {
                "documentId": document_id,
            })
        except Exception as exc:
            cleanup_error = str(exc)[:500]
            self.mysql.execute(
                "UPDATE agent_approval SET cleanup_status = 'FAILED' WHERE id = %s",
                (approval_id,),
            )
            self.audit(run_id, approval["trace_id"], "CLEANUP_FAILED", {
                "documentId": document_id,
                "error": cleanup_error,
            })

        self._complete(approval_id, run_id)
        return {
            "status": "completed",
            "documentId": document_id,
            "alreadyDeleted": already_deleted,
            "cleanupError": cleanup_error,
        }

    def _cleanup(self, document_id: int, file_path: Optional[str]) -> None:
        self.vector_store.delete_document(document_id)
        if file_path and not file_path.startswith(("http://", "https://")) and os.path.exists(file_path):
            os.remove(file_path)

    def _complete(self, approval_id: str, run_id: str) -> None:
        self.mysql.execute(
            "UPDATE agent_approval SET execution_status = 'COMPLETED' WHERE id = %s",
            (approval_id,),
        )

    def audit(self, run_id: str, trace_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        self.mysql.execute(
            """
            INSERT INTO agent_audit_event
                (run_id, trace_id, event_type, payload_json, created_at)
            VALUES (%s, %s, %s, %s, NOW())
            """,
            (run_id, trace_id, event_type, json.dumps(payload, ensure_ascii=False)),
        )
