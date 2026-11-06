import hashlib
from pathlib import Path

import pytest
from langchain_core.documents import Document

from core.reindex import rebuild_index
from core.vector_store import VectorStoreManager
from tests.test_vector_store import FixedEmbeddings


class FakeSource:
    def __init__(self, documents, orphan_report=None):
        self.documents = documents
        self.orphan_report = orphan_report or {}

    def get_active_chunks(self):
        return list(self.documents)

    def get_orphan_report(self):
        return dict(self.orphan_report)

    def get_duplicate_report(self):
        return []


def active_document(doc_id, content):
    return Document(
        page_content=content,
        metadata={
            "doc_id": doc_id,
            "chunk_id": doc_id * 100,
            "chunk_index": 0,
            "source": f"document-{doc_id}.txt",
        },
    )


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_dry_run_reports_scope_without_creating_or_replacing_index(tmp_path):
    target = tmp_path / "faiss_index"
    source = FakeSource(
        [active_document(1, "事务 ACID 测试内容")],
        orphan_report={91: 2, 92: 3},
    )

    report = rebuild_index(
        source=source,
        embeddings=FixedEmbeddings(dimension=8),
        target_dir=target,
        apply=False,
        embedding_provider="local",
        embedding_model="fake-model",
    )

    assert report["mode"] == "dry-run"
    assert report["active_document_count"] == 1
    assert report["active_chunk_count"] == 1
    assert report["orphan_chunk_count"] == 5
    assert report["orphan_documents"] == {"91": 2, "92": 3}
    assert target.exists() is False


def test_apply_keeps_timestamped_backup_and_activates_rebuilt_index(tmp_path):
    target = tmp_path / "faiss_index"
    embeddings = FixedEmbeddings(dimension=8)
    original = VectorStoreManager(
        persist_directory=str(target),
        use_milvus=False,
        embeddings=embeddings,
        reranker=None,
    )
    original.add_documents([active_document(9, "旧索引内容")])
    original_hash = file_hash(target / "index.faiss")

    report = rebuild_index(
        source=FakeSource([active_document(1, "事务 ACID 测试内容")]),
        embeddings=embeddings,
        target_dir=target,
        apply=True,
        embedding_provider="local",
        embedding_model="fake-model",
    )

    backup = Path(report["backup_directory"])
    assert backup.is_dir()
    assert file_hash(backup / "index.faiss") == original_hash
    rebuilt = VectorStoreManager(
        persist_directory=str(target),
        use_milvus=False,
        embeddings=embeddings,
        reranker=None,
        embedding_provider="local",
        embedding_model="fake-model",
    )
    assert rebuilt.get_health()["status"] == "HEALTHY"
    assert rebuilt.search(
        "事务 ACID 是什么", similarity_threshold=0.7, use_rerank=False
    )[0].metadata["doc_id"] == 1


def test_failed_validation_leaves_active_index_untouched(tmp_path):
    target = tmp_path / "faiss_index"
    embeddings = FixedEmbeddings(dimension=8)
    original = VectorStoreManager(
        persist_directory=str(target),
        use_milvus=False,
        embeddings=embeddings,
        reranker=None,
    )
    original.add_documents([active_document(9, "旧索引内容")])
    original_hash = file_hash(target / "index.faiss")

    def reject(_report):
        raise RuntimeError("validation rejected")

    with pytest.raises(RuntimeError, match="validation rejected"):
        rebuild_index(
            source=FakeSource([active_document(1, "事务 ACID 测试内容")]),
            embeddings=embeddings,
            target_dir=target,
            apply=True,
            embedding_provider="local",
            embedding_model="fake-model",
            validator=reject,
        )

    assert file_hash(target / "index.faiss") == original_hash
    assert list(tmp_path.glob("faiss_index.backup-*")) == []
