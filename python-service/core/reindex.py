from datetime import datetime
import hashlib
from pathlib import Path
import shutil
import uuid
from typing import Callable, Dict, Iterable, List, Optional

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from core.vector_store import VectorStoreManager


class RebuildValidationError(RuntimeError):
    pass


class MySQLChunkSource:
    """Load the default rebuild scope from authoritative MySQL state."""

    def __init__(self, mysql):
        self.mysql = mysql

    def get_active_chunks(self) -> List[Document]:
        rows = self.mysql.fetch_all(
            """
            SELECT d.id AS doc_id, d.doc_name, d.file_path,
                   c.id AS chunk_id, c.chunk_index, c.chunk_text
            FROM knowledge_doc d
            JOIN knowledge_chunk c ON c.doc_id = d.id
            WHERE d.status = 'COMPLETED'
              AND c.chunk_text IS NOT NULL
              AND TRIM(c.chunk_text) <> ''
            ORDER BY d.id, c.chunk_index, c.id
            """,
            raise_on_error=True,
        )
        return [
            Document(
                page_content=row["chunk_text"],
                metadata={
                    "doc_id": row["doc_id"],
                    "chunk_id": row["chunk_id"],
                    "chunk_index": row["chunk_index"],
                    "source": row.get("file_path") or row.get("doc_name"),
                    "doc_name": row.get("doc_name"),
                },
            )
            for row in rows
        ]

    def get_orphan_report(self) -> Dict[str, int]:
        rows = self.mysql.fetch_all(
            """
            SELECT c.doc_id, COUNT(*) AS chunk_count
            FROM knowledge_chunk c
            LEFT JOIN knowledge_doc d ON d.id = c.doc_id
            WHERE d.id IS NULL
            GROUP BY c.doc_id
            ORDER BY c.doc_id
            """,
            raise_on_error=True,
        )
        return {str(row["doc_id"]): int(row["chunk_count"]) for row in rows}

    def get_duplicate_report(self) -> List[Dict[str, int]]:
        rows = self.mysql.fetch_all(
            """
            SELECT doc_id, chunk_index, COUNT(*) AS occurrences
            FROM knowledge_chunk
            GROUP BY doc_id, chunk_index
            HAVING COUNT(*) > 1
            ORDER BY doc_id, chunk_index
            """,
            raise_on_error=True,
        )
        return [
            {
                "doc_id": int(row["doc_id"]),
                "chunk_index": int(row["chunk_index"]),
                "occurrences": int(row["occurrences"]),
            }
            for row in rows
        ]


def _deduplicate(documents: Iterable[Document]):
    unique: List[Document] = []
    seen = set()
    duplicates = 0
    for document in documents:
        doc_id = document.metadata.get("doc_id")
        content_hash = hashlib.sha256(document.page_content.encode("utf-8")).hexdigest()
        identity = (doc_id, content_hash)
        if identity in seen:
            duplicates += 1
            continue
        seen.add(identity)
        unique.append(document)
    return unique, duplicates


def _default_validator(manager: VectorStoreManager, expected_chunks: int, documents: List[Document]):
    health = manager.get_health()
    if health["status"] not in {"HEALTHY", "EMPTY"}:
        raise RebuildValidationError(health["message"])
    if manager.vector_store is not None and int(manager.vector_store.index.ntotal) != expected_chunks:
        raise RebuildValidationError(
            f"expected {expected_chunks} vectors, found "
            f"{manager.vector_store.index.ntotal}"
        )
    if documents:
        query = documents[0].page_content[:200]
        results = manager.search(query, k=1, similarity_threshold=0.5, use_rerank=False)
        if not results:
            raise RebuildValidationError("rebuilt index could not retrieve its own fixture")


def rebuild_index(
    *,
    source,
    embeddings: Optional[Embeddings],
    target_dir: str | Path,
    apply: bool = False,
    embedding_provider: str = "local",
    embedding_model: str = "BAAI/bge-small-zh-v1.5",
    validator: Optional[Callable[[Dict], None]] = None,
) -> Dict:
    """
    Build a replacement index from active completed documents.

    Dry-run is the default. Apply mode validates a temporary index before
    retaining the old index as a timestamped backup and activating the new one.
    """
    target = Path(target_dir).resolve()
    documents, content_duplicates = _deduplicate(source.get_active_chunks())
    orphan_report = {
        str(doc_id): int(count)
        for doc_id, count in source.get_orphan_report().items()
    }
    duplicate_report = list(source.get_duplicate_report())
    active_document_ids = {
        document.metadata.get("doc_id")
        for document in documents
        if document.metadata.get("doc_id") is not None
    }
    report = {
        "mode": "apply" if apply else "dry-run",
        "target_directory": str(target),
        "embedding_provider": embedding_provider,
        "embedding_model": embedding_model,
        "active_document_count": len(active_document_ids),
        "active_chunk_count": len(documents),
        "orphan_documents": orphan_report,
        "orphan_chunk_count": sum(orphan_report.values()),
        "duplicate_chunk_indexes": duplicate_report,
        "duplicate_content_chunks": content_duplicates,
        "source_policy": "active_completed",
    }
    if embeddings is not None:
        report["embedding_dimension"] = len(embeddings.embed_query("dimension probe"))
    if not apply:
        return report
    if embeddings is None:
        raise ValueError("embeddings are required when applying an index rebuild")

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.rebuild-{uuid.uuid4().hex}")
    backup = None

    try:
        manager = VectorStoreManager(
            persist_directory=str(temporary),
            use_milvus=False,
            embeddings=embeddings,
            reranker=None,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
        )
        manager.add_documents(documents)
        if not documents:
            manager.create_empty_index()

        _default_validator(manager, len(documents), documents)
        report["built_chunk_count"] = len(documents)
        if validator:
            validator(report)

        if target.exists():
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            backup = target.with_name(f"{target.name}.backup-{timestamp}-{uuid.uuid4().hex[:8]}")
            target.rename(backup)
        try:
            temporary.rename(target)
        except Exception:
            if backup is not None and backup.exists() and not target.exists():
                backup.rename(target)
            raise

        report["backup_directory"] = str(backup) if backup else None
        report["status"] = "activated"
        return report
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def rebuild_from_mysql(
    mysql,
    *,
    embeddings: Optional[Embeddings],
    target_dir: str | Path,
    apply: bool = False,
    embedding_provider: str = "local",
    embedding_model: str = "BAAI/bge-small-zh-v1.5",
):
    return rebuild_index(
        source=MySQLChunkSource(mysql),
        embeddings=embeddings,
        target_dir=target_dir,
        apply=apply,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
    )
