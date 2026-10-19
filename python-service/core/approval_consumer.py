import json
import logging
from typing import Any, Dict

from core.approval_execution import ApprovalExecutionError, ApprovalExecutionService
from core.message_contract import MessageContractError, validate_approval_decision


class ApprovalDecisionHandler:
    def __init__(self, executor: ApprovalExecutionService, registry=None):
        self.executor = executor
        self.registry = registry

    def handle(self, body: bytes) -> Dict[str, Any]:
        try:
            message = validate_approval_decision(json.loads(body.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, MessageContractError) as exc:
            logging.error("Rejecting malformed approval decision: %s", exc)
            return {"status": "invalid_message"}

        if message["decision"] == "REJECTED":
            self.executor.audit(
                message["runId"],
                message.get("traceId", ""),
                "REJECTION_RESUME_ACKNOWLEDGED",
                {"approvalId": message["approvalId"], "documentId": message["documentId"]},
            )
            return {"status": "rejected"}

        try:
            parameters = {
                "documentId": message["documentId"],
                "approvalId": message["approvalId"],
                "runId": message["runId"],
            }
            if self.registry is None:
                return self.executor.execute(message)
            return self.registry.invoke_tool(
                "delete_document",
                parameters,
                run_id=message["runId"],
                execution_context={
                    "approval_id": message["approvalId"],
                    "run_id": message["runId"],
                },
                approval_validator=self.executor.validate_and_claim,
            )
        except ApprovalExecutionError as exc:
            self.executor.audit(
                message["runId"],
                message.get("traceId", ""),
                "APPROVAL_ENFORCEMENT_REJECTED",
                {"approvalId": message["approvalId"], "reason": str(exc)},
            )
            return {"status": "rejected_by_tool_boundary"}
        except PermissionError as exc:
            self.executor.audit(
                message["runId"],
                message.get("traceId", ""),
                "APPROVAL_ENFORCEMENT_REJECTED",
                {"approvalId": message["approvalId"], "reason": str(exc)},
            )
            return {"status": "rejected_by_tool_boundary"}
        except Exception as exc:
            self.executor.mysql.execute(
                "UPDATE agent_approval SET publication_status = 'QUEUED' WHERE id = %s",
                (message["approvalId"],),
            )
            self.executor.audit(
                message["runId"],
                message.get("traceId", ""),
                "APPROVAL_RESUME_FAILED",
                {"approvalId": message["approvalId"], "reason": str(exc)[:500]},
            )
            return {"status": "resume_failed"}
