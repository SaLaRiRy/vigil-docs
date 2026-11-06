import os

os.environ.setdefault("VECTOR_STORE_DISABLE_GLOBAL_INIT", "1")

import faiss
import numpy as np
import pytest
from langchain_community.vectorstores import FAISS
from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from core.vector_index import IndexManifest, VectorIndexUnavailableError, write_manifest
from core.vector_store import VectorStoreManager


class FixedEmbeddings(Embeddings):
    def __init__(self, dimension: int, query_vector: list[float] | None = None):
        self.dimension = dimension
        self.query_vector = query_vector or [1.0] + [0.0] * (dimension - 1)

    def embed_documents(self, texts):
        return [
            [1.0] + [0.0] * (self.dimension - 1)
            if "ACID" in text or "事务" in text
            else [0.0] * (self.dimension - 1) + [1.0]
            for text in texts
        ]

    def embed_query(self, text):
        return self.query_vector


class RelatedQueryEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [
            [1.0, 0.0] if "ACID" in text or "事务" in text else [0.0, 1.0]
            for text in texts
        ]

    def embed_query(self, text):
        return [0.6, 0.8]


def write_index(path, dimension: int):
    docstore = InMemoryDocstore(
        {"doc-1": Document(page_content="事务 ACID 测试内容", metadata={"doc_id": 1})}
    )
    index = faiss.IndexFlatL2(dimension)
    index.add(np.asarray([[1.0] + [0.0] * (dimension - 1)], dtype=np.float32))
    store = FAISS(
        embedding_function=FixedEmbeddings(dimension),
        index=index,
        docstore=docstore,
        index_to_docstore_id={0: "doc-1"},
    )
    store.save_local(str(path))


def test_incompatible_index_is_unavailable_instead_of_returning_empty_results(tmp_path):
    index_path = tmp_path / "faiss_index"
    write_index(index_path, dimension=4)

    manager = VectorStoreManager(
        persist_directory=str(index_path),
        use_milvus=False,
        embeddings=FixedEmbeddings(dimension=8),
        reranker=None,
    )

    assert manager.get_health()["status"] == "UNAVAILABLE"
    with pytest.raises(VectorIndexUnavailableError):
        manager.search("事务 ACID 是什么", similarity_threshold=0.7, use_rerank=False)


def test_l2_index_is_unavailable_even_when_manifest_dimensions_match(tmp_path):
    index_path = tmp_path / "faiss_index"
    write_index(index_path, dimension=4)
    write_manifest(
        index_path,
        IndexManifest.build(
            embedding_provider="local",
            embedding_model="fake-model",
            embedding_dimension=4,
            document_count=1,
            chunk_count=1,
            score_metric="cosine",
        ),
    )

    manager = VectorStoreManager(
        persist_directory=str(index_path),
        use_milvus=False,
        embeddings=FixedEmbeddings(dimension=4),
        reranker=None,
        embedding_provider="local",
        embedding_model="fake-model",
    )

    assert manager.get_health()["status"] == "UNAVAILABLE"
    assert "cosine" in manager.get_health()["message"]


def test_relevant_document_passes_production_similarity_threshold(tmp_path):
    manager = VectorStoreManager(
        persist_directory=str(tmp_path / "faiss_index"),
        use_milvus=False,
        embeddings=FixedEmbeddings(dimension=8),
        reranker=None,
    )
    manager.add_documents(
        [
            Document(
                page_content="事务 ACID 包含原子性、一致性、隔离性和持久性。",
                metadata={"doc_id": 42, "chunk_index": 0},
            )
        ]
    )

    results = manager.search(
        "事务 ACID 是什么", similarity_threshold=0.7, use_rerank=False
    )

    assert [document.metadata["doc_id"] for document in results] == [42]
    assert results[0].metadata["score"] >= 0.7


def test_semantically_related_cosine_passes_default_threshold(tmp_path):
    manager = VectorStoreManager(
        persist_directory=str(tmp_path / "faiss_index"),
        use_milvus=False,
        embeddings=RelatedQueryEmbeddings(),
        reranker=None,
    )
    manager.add_documents(
        [
            Document(
                page_content="事务 ACID 包含原子性和一致性。",
                metadata={"doc_id": 42, "chunk_id": 420, "chunk_index": 0},
            )
        ]
    )

    results = manager.search("事务 ACID 是什么", use_rerank=False)

    assert [document.metadata["doc_id"] for document in results] == [42]
    assert 0.5 <= results[0].metadata["score"] < 0.7


def test_unrelated_document_is_a_healthy_no_match(tmp_path):
    manager = VectorStoreManager(
        persist_directory=str(tmp_path / "faiss_index"),
        use_milvus=False,
        embeddings=FixedEmbeddings(
            dimension=8,
            query_vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        ),
        reranker=None,
    )
    manager.add_documents(
        [
            Document(
                page_content="天气预报显示明天有雨。",
                metadata={"doc_id": 7, "chunk_index": 0},
            )
        ]
    )

    assert manager.get_health()["status"] == "HEALTHY"
    assert manager.search(
        "事务 ACID 是什么", similarity_threshold=0.7, use_rerank=False
    ) == []


def test_empty_index_is_healthy_but_has_no_results(tmp_path):
    manager = VectorStoreManager(
        persist_directory=str(tmp_path / "faiss_index"),
        use_milvus=False,
        embeddings=FixedEmbeddings(dimension=8),
        reranker=None,
    )

    assert manager.get_health()["status"] == "EMPTY"
    assert manager.search(
        "事务 ACID 是什么", similarity_threshold=0.7, use_rerank=False
    ) == []


def test_manifest_and_cosine_index_survive_reload(tmp_path):
    index_path = tmp_path / "faiss_index"
    embeddings = FixedEmbeddings(dimension=8)
    manager = VectorStoreManager(
        persist_directory=str(index_path),
        use_milvus=False,
        embeddings=embeddings,
        reranker=None,
    )
    manager.add_documents(
        [
            Document(
                page_content="事务 ACID 包含原子性、一致性、隔离性和持久性。",
                metadata={"doc_id": 42, "chunk_index": 0},
            )
        ]
    )

    reloaded = VectorStoreManager(
        persist_directory=str(index_path),
        use_milvus=False,
        embeddings=embeddings,
        reranker=None,
    )

    assert reloaded.get_health()["status"] == "HEALTHY"
    assert reloaded.get_health()["document_count"] == 1
    assert reloaded.get_health()["indexedDocumentIds"] == [42]
    assert reloaded.search(
        "事务 ACID 是什么", similarity_threshold=0.7, use_rerank=False
    )[0].metadata["doc_id"] == 42


def test_document_deletion_updates_manifest_counts(tmp_path):
    index_path = tmp_path / "faiss_index"
    embeddings = FixedEmbeddings(dimension=8)
    manager = VectorStoreManager(
        persist_directory=str(index_path),
        use_milvus=False,
        embeddings=embeddings,
        reranker=None,
    )
    manager.add_documents(
        [
            Document(
                page_content="事务 ACID 测试内容",
                metadata={"doc_id": 42, "chunk_id": 420, "chunk_index": 0},
            )
        ]
    )

    manager.delete_document(42)

    reloaded = VectorStoreManager(
        persist_directory=str(index_path),
        use_milvus=False,
        embeddings=embeddings,
        reranker=None,
    )
    health = reloaded.get_health()
    assert health["status"] == "EMPTY"
    assert health["document_count"] == 0
    assert health["chunk_count"] == 0
