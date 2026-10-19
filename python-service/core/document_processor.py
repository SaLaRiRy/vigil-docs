import logging
from typing import Any, Dict

from core.message_contract import validate_document_message

logger = logging.getLogger(__name__)


class DocumentNotFoundError(RuntimeError):
    pass


class DocumentProcessor:
    def __init__(self, parser, mysql, vector_store, max_attempts: int = 3):
        self.parser = parser
        self.mysql = mysql
        self.vector_store = vector_store
        self.max_attempts = max_attempts

    def process(self, raw_message: Dict[str, Any]) -> str:
        message = validate_document_message(raw_message)
        document_id = message["documentId"]
        document = self.mysql.get_document(document_id)
        if not document:
            raise DocumentNotFoundError(f"Document {document_id} does not exist")
        if document["status"] == "DELETED":
            return "already_deleted"

        attempt = self.mysql.increment_processing_attempt(document_id)
        if self.mysql.mark_processing(document_id) != 1:
            return "state_changed"
        try:
            chunks = self.parser.parse(message["storagePath"])
            for index, chunk in enumerate(chunks):
                chunk.metadata["doc_id"] = document_id
                chunk.metadata["source"] = message["storagePath"]
                chunk.metadata["chunk_index"] = index

            # Replace this document's vectors before adding the new set so a
            # re-delivery cannot leave duplicate vectors behind.
            self.vector_store.delete_document(document_id)
            self.vector_store.add_documents(chunks)
            self.mysql.complete_document(
                document_id,
                [
                    {
                        "page_content": chunk.page_content,
                        "chunk_index": index,
                    }
                    for index, chunk in enumerate(chunks)
                ],
            )
            return "completed"
        except Exception as exc:
            safe_error = "Document could not be parsed or indexed"
            is_final = attempt >= self.max_attempts
            if is_final:
                self.mysql.mark_failed(document_id, safe_error, dead_lettered=True)
            else:
                self.mysql.mark_retry_pending(document_id, safe_error)
            logger.warning(
                "Document %s processing failed on attempt %s/%s",
                document_id,
                attempt,
                self.max_attempts,
                exc_info=True,
            )
            raise ProcessingAttemptFailed(
                document_id=document_id,
                attempt=attempt,
                final=is_final,
                reason=str(exc),
            ) from exc


class ProcessingAttemptFailed(RuntimeError):
    def __init__(self, document_id: int, attempt: int, final: bool, reason: str):
        super().__init__(reason)
        self.document_id = document_id
        self.attempt = attempt
        self.final = final
