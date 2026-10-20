from typing import Any, Dict

from tools.base import SchemaProperty, Tool, ToolMetadata, ToolSchema


class DeleteDocumentTool(Tool):
    def __init__(self, execution_service):
        self.execution_service = execution_service
        super().__init__(
            name="delete_document",
            description="Soft-delete one explicitly selected document with a valid approval ticket.",
            input_schema=ToolSchema(
                properties={
                    "documentId": SchemaProperty(type="number", description="Explicit selected document ID"),
                    "approvalId": SchemaProperty(type="string", description="Approval ticket ID"),
                    "runId": SchemaProperty(type="string", description="Bound run ID"),
                }
            ),
            output_schema=ToolSchema(
                properties={
                    "status": SchemaProperty(type="string", description="Deletion result"),
                    "documentId": SchemaProperty(type="number", description="Deleted document ID"),
                }
            ),
            metadata=ToolMetadata(
                timeout_ms=30000,
                max_retries=0,
                permission="destructive",
                description="Requires an approval bound to the same run and document.",
            ),
        )

    def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        return self.execution_service.execute(
            {
                "approvalId": parameters["approvalId"],
                "runId": parameters["runId"],
                "documentId": int(parameters["documentId"]),
            }
        )
