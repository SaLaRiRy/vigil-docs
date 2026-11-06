import os
import shutil
from typing import List, Optional, Dict, Any
import faiss
from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_community.embeddings import DashScopeEmbeddings, HuggingFaceEmbeddings
from langchain_core.documents import Document
from core.reranker import create_reranker, BaseReranker
from core.config import config
from core.vector_index import (
    IndexManifest,
    NormalizedEmbeddings,
    VectorIndexUnavailableError,
    load_manifest,
    write_manifest,
)

# pymilvus 和 Milvus 是可选依赖，仅在使用 Milvus 时需要
try:
    from pymilvus import connections, utility
    from langchain_community.vectorstores import Milvus
    MILVUS_AVAILABLE = True
except ImportError:
    MILVUS_AVAILABLE = False


_UNSET = object()


def create_embeddings():
    """Build the configured embedding client and its manifest identity."""
    configured_embedding_model = config.EMBEDDING_MODEL.lower()
    if configured_embedding_model == "local":
        local_model = config.LOCAL_EMBEDDING_MODEL
        config.logger.info(f"Using local HuggingFace Embeddings ({local_model})")
        return (
            HuggingFaceEmbeddings(model_name=local_model),
            "local",
            local_model,
        )

    api_key = config.DASHSCOPE_API_KEY
    if api_key:
        config.logger.info("Using DashScope Embeddings (text-embedding-v1)")
        return (
            DashScopeEmbeddings(
                model="text-embedding-v1",
                dashscope_api_key=api_key,
            ),
            "dashscope",
            "text-embedding-v1",
        )

    config.logger.warning(
        "DASHSCOPE_API_KEY not found. Falling back to local HuggingFace Embeddings."
    )
    return (
        HuggingFaceEmbeddings(model_name=config.LOCAL_EMBEDDING_MODEL),
        "local",
        config.LOCAL_EMBEDDING_MODEL,
    )


class VectorStoreManager:
    def __init__(
        self,
        persist_directory=None,
        use_milvus=None,
        *,
        embeddings=None,
        reranker=_UNSET,
        embedding_provider=None,
        embedding_model=None,
    ):
        """
        初始化向量存储管理器

        Args:
            persist_directory: FAISS持久化目录（仅当use_milvus=False时使用）
            use_milvus: 是否使用Milvus（默认从环境变量读取，默认值为True）
        """
        # 从环境变量读取持久化目录，默认值为./faiss_index
        self.persist_directory = persist_directory or config.VECTOR_STORE_PERSIST_DIR
        # 从环境变量读取use_milvus配置，如果未设置则默认为True
        if use_milvus is None:
            use_milvus = config.USE_MILVUS
        self.use_milvus = use_milvus
        # 从环境变量读取集合名称，默认值为ai_knowledge_collection
        self.collection_name = config.VECTOR_STORE_COLLECTION_NAME
        self.vector_store = None
        self.manifest = None
        self._embedding_dimension_value = None
        self._health_status = "UNAVAILABLE"
        self._health_message = "Vector store has not been initialized"

        # 初始化Reranker
        if reranker is _UNSET:
            self._init_reranker()
        else:
            self.reranker = reranker

        if embeddings is not None:
            base_embeddings = embeddings
            self.embedding_provider = embedding_provider or config.EMBEDDING_MODEL.lower()
            self.embedding_model = embedding_model or config.LOCAL_EMBEDDING_MODEL
        else:
            base_embeddings, detected_provider, detected_model = create_embeddings()
            self.embedding_provider = embedding_provider or detected_provider
            self.embedding_model = embedding_model or detected_model

        self.embeddings = NormalizedEmbeddings(base_embeddings)

        # 如果 pymilvus 未安装，强制使用 FAISS
        if self.use_milvus and not MILVUS_AVAILABLE:
            config.logger.warning("pymilvus not installed, falling back to FAISS")
            self.use_milvus = False

        # 根据配置选择向量数据库
        if self.use_milvus:
            self._init_milvus()
        else:
            self._init_faiss()

    def _init_reranker(self):
        """初始化Reranker"""
        reranker_type = config.RERANKER_TYPE
        if reranker_type == "none":
            self.reranker = None
            config.logger.info("Reranker is disabled")
            return

        try:
            self.reranker = create_reranker(reranker_type)
            config.logger.info(f"Reranker initialized: {reranker_type}")
        except Exception as e:
            config.logger.error(f"Failed to initialize reranker: {e}")
            self.reranker = None

    def _init_milvus(self):
        """初始化Milvus连接和集合"""
        try:
            # Milvus连接配置
            milvus_host = config.MILVUS_HOST
            milvus_port = config.MILVUS_PORT

            config.logger.info(f"Connecting to Milvus at {milvus_host}:{milvus_port}")
            connections.connect(alias="default", host=milvus_host, port=milvus_port)

            # 检查连接
            if not connections.has_connection("default"):
                raise ConnectionError("Failed to connect to Milvus")

            config.logger.info("Successfully connected to Milvus")

            # 初始化Milvus向量存储
            self.vector_store = Milvus(
                embedding_function=self.embeddings,
                collection_name=self.collection_name,
                connection_args={
                    "host": milvus_host,
                    "port": milvus_port,
                    "alias": "default"
                },
                # 自动创建集合（如果不存在）
                auto_id=True
            )

            config.logger.info(f"Milvus collection '{self.collection_name}' ready")

        except Exception as e:
            config.logger.error(f"Failed to initialize Milvus: {e}")
            config.logger.info("Falling back to FAISS...")
            self.use_milvus = False
            self._init_faiss()

    def _init_faiss(self):
        """
        初始化 FAISS 向量存储（作为 Milvus 的 fallback）
        """
        config.logger.info("Using FAISS vector store (fallback mode)")
        if os.path.exists(self.persist_directory):
            try:
                self.vector_store = FAISS.load_local(self.persist_directory, self.embeddings, allow_dangerous_deserialization=True)
                config.logger.info(f"Loaded existing FAISS index from {self.persist_directory}")
            except Exception as e:
                config.logger.error(f"Error loading existing FAISS index: {e}")
                self.vector_store = None
                self._health_status = "UNAVAILABLE"
                self._health_message = f"无法加载向量索引: {e}"
                return
        else:
            self.vector_store = None
            self._health_status = "EMPTY"
            self._health_message = "尚未创建向量索引"
            config.logger.info("No existing FAISS index found, will create new one when needed")
            return

        try:
            self.manifest = load_manifest(self.persist_directory)
        except Exception as e:
            self._health_status = "UNAVAILABLE"
            self._health_message = f"索引 manifest 无效: {e}"
            return

        if self.manifest is None:
            self._health_status = "UNAVAILABLE"
            self._health_message = "索引缺少 manifest，需要重新构建"
            return

        expected_dimension = self.embedding_dimension
        actual_dimension = int(self.vector_store.index.d)
        if not self.manifest.is_compatible(
            embedding_provider=self.embedding_provider,
            embedding_model=self.embedding_model,
            embedding_dimension=expected_dimension,
        ):
            self._health_status = "UNAVAILABLE"
            self._health_message = (
                f"索引与当前 embedding 不兼容 "
                f"(manifest: {self.manifest.embedding_model}/{self.manifest.embedding_dimension}, "
                f"current: {self.embedding_model}/{expected_dimension})"
            )
            return

        if actual_dimension != expected_dimension:
            self._health_status = "UNAVAILABLE"
            self._health_message = (
                f"索引维度 {actual_dimension} 与 embedding 维度 "
                f"{expected_dimension} 不匹配"
            )
            return

        if not isinstance(self.vector_store.index, faiss.IndexFlatIP):
            self._health_status = "UNAVAILABLE"
            self._health_message = "索引不是 cosine/inner-product 度量，需要重新构建"
            return

        if int(self.vector_store.index.ntotal) == 0:
            self._health_status = "EMPTY"
            self._health_message = "向量索引为空"
        else:
            self._health_status = "HEALTHY"
            self._health_message = "向量索引可检索"

    @property
    def embedding_dimension(self) -> int:
        if self._embedding_dimension_value is None:
            vector = self.embeddings.embed_query("embedding dimension probe")
            self._embedding_dimension_value = len(vector)
        return self._embedding_dimension_value

    def get_health(self) -> Dict[str, Any]:
        if self.use_milvus:
            status = "HEALTHY" if self.vector_store is not None else "UNAVAILABLE"
            return {
                "status": status,
                "message": "Milvus 已连接" if status == "HEALTHY" else "Milvus 不可用",
                "backend": "milvus",
                "model": self.embedding_model,
                "provider": self.embedding_provider,
            }

        actual_dimension = None
        if self.vector_store is not None and hasattr(self.vector_store, "index"):
            actual_dimension = int(self.vector_store.index.d)
        return {
            "status": self._health_status,
            "message": self._health_message,
            "backend": "faiss",
            "dimension": actual_dimension,
            "expected_dimension": self.embedding_dimension,
            "model": self.embedding_model,
            "provider": self.embedding_provider,
            "document_count": self.manifest.document_count if self.manifest else 0,
            "chunk_count": int(self.vector_store.index.ntotal)
            if self.vector_store is not None and hasattr(self.vector_store, "index")
            else 0,
            "source_policy": self.manifest.source_policy if self.manifest else None,
        }

    def add_documents(self, documents: List[Document]):
        """
        添加文档到向量数据库
        """
        if not documents:
            return
        health = self.get_health()
        if health["status"] == "UNAVAILABLE":
            raise VectorIndexUnavailableError(health["message"])

        if self.vector_store is None:
            if self.use_milvus:
                # Milvus会自动创建集合
                milvus_host = config.MILVUS_HOST
                milvus_port = config.MILVUS_PORT
                self.vector_store = Milvus.from_documents(
                    documents=documents,
                    embedding=self.embeddings,
                    collection_name=self.collection_name,
                    connection_args={
                        "host": milvus_host,
                        "port": milvus_port,
                        "alias": "default"
                    }
                )
                config.logger.info(f"Created Milvus collection '{self.collection_name}' with {len(documents)} documents")
            else:
                texts = [document.page_content for document in documents]
                vectors = self.embeddings.embed_documents(texts)
                text_embeddings = zip(texts, vectors)
                metadata = [document.metadata for document in documents]
                ids = [self._document_id(document, index) for index, document in enumerate(documents)]
                self.vector_store = FAISS.from_embeddings(
                    text_embeddings,
                    self.embeddings,
                    metadatas=metadata,
                    ids=ids,
                    distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT,
                )
                self._save_faiss()
                config.logger.info(f"Created FAISS cosine index with {len(documents)} documents")
        else:
            # 添加文档到现有存储
            if self.use_milvus:
                # Milvus添加文档
                self.vector_store.add_documents(documents)
                config.logger.info(f"Added {len(documents)} documents to Milvus")
            else:
                texts = [document.page_content for document in documents]
                text_embeddings = zip(texts, self.embeddings.embed_documents(texts))
                metadata = [document.metadata for document in documents]
                ids = [self._document_id(document, index) for index, document in enumerate(documents)]
                self.vector_store.add_embeddings(
                    text_embeddings,
                    metadatas=metadata,
                    ids=ids,
                )
                self._save_faiss()
                config.logger.info(f"Added {len(documents)} documents to FAISS cosine index")

    @staticmethod
    def _document_id(document: Document, fallback_index: int) -> str:
        metadata = document.metadata or {}
        doc_id = metadata.get("doc_id")
        chunk_index = metadata.get("chunk_index", fallback_index)
        chunk_id = metadata.get("chunk_id")
        if chunk_id is not None:
            return f"doc-{doc_id}-chunk-row-{chunk_id}"
        if doc_id is not None:
            return f"doc-{doc_id}-chunk-{chunk_index}"
        source = metadata.get("source")
        if source:
            return f"{source}-chunk-{chunk_index}"
        return f"chunk-{fallback_index}"

    def create_empty_index(self):
        """Create a valid, compatible FAISS index with zero vectors."""
        if self.use_milvus:
            raise VectorIndexUnavailableError(
                "create_empty_index is only supported for FAISS"
            )
        self.vector_store = FAISS(
            embedding_function=self.embeddings,
            index=faiss.IndexFlatIP(self.embedding_dimension),
            docstore=InMemoryDocstore(),
            index_to_docstore_id={},
            distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT,
        )
        self._save_faiss()

    def _save_faiss(self):
        self.vector_store.save_local(self.persist_directory)
        documents = list(self.vector_store.docstore._dict.values())
        document_ids = {
            document.metadata.get("doc_id")
            for document in documents
            if document.metadata.get("doc_id") is not None
        }
        manifest = IndexManifest.build(
            embedding_provider=self.embedding_provider,
            embedding_model=self.embedding_model,
            embedding_dimension=self.embedding_dimension,
            document_count=len(document_ids),
            chunk_count=int(self.vector_store.index.ntotal),
            source_policy="active_completed",
            score_metric="cosine",
        )
        write_manifest(self.persist_directory, manifest)
        self.manifest = manifest
        self._health_status = "HEALTHY" if self.vector_store.index.ntotal else "EMPTY"
        self._health_message = "向量索引可检索" if self.vector_store.index.ntotal else "向量索引为空"

    def search(self, query: str, k: int = 3, filter_dict: Optional[Dict[str, Any]] = None, similarity_threshold: float = 0.75, use_rerank: bool = True) -> List[Document]:
        """
        相似度搜索

        Args:
            query: 查询文本
            k: 返回结果数量
            filter_dict: 过滤条件（仅Milvus支持）
            similarity_threshold: 相似度阈值，只有相似度大于此值的文档才返回（0.0-1.0）
            use_rerank: 是否使用Rerank进行结果重排序
        """
        import time
        start_time = time.time()

        health = self.get_health()
        if health["status"] == "UNAVAILABLE":
            raise VectorIndexUnavailableError(health["message"])

        if self.vector_store is None or health["status"] == "EMPTY":
            config.logger.info(f"Search completed in {time.time() - start_time:.4f}s, no vector store available")
            return []

        try:
            # 初始检索数量应该比最终返回的多，以便Rerank有足够的候选
            initial_k = k * 3 if use_rerank and self.reranker else k

            search_start = time.time()
            if self.use_milvus and filter_dict:
                # Milvus支持过滤查询
                docs_with_scores = self.vector_store.similarity_search_with_score(query, k=initial_k, filter=filter_dict)
            else:
                # FAISS或无条件查询
                docs_with_scores = self.vector_store.similarity_search_with_score(query, k=initial_k)
            search_time = time.time() - search_start
            config.logger.info(f"Vector search completed in {search_time:.4f}s, found {len(docs_with_scores) if isinstance(docs_with_scores, list) else 0} documents")

            # 提取文档
            if isinstance(docs_with_scores, list):
                if len(docs_with_scores) > 0 and isinstance(docs_with_scores[0], tuple):
                    # (doc, score) 格式
                    docs = [doc for doc, score in docs_with_scores]
                else:
                    docs = docs_with_scores
            else:
                docs = docs_with_scores

            # 如果没有启用Rerank或没有Reranker，直接返回初步检索结果
            if not use_rerank or not self.reranker:
                # 过滤掉相似度低于阈值的文档
                filtered_docs = []
                for i, (doc, score) in enumerate(docs_with_scores):
                    if score >= similarity_threshold:
                        doc.metadata = dict(doc.metadata or {})
                        doc.metadata["score"] = float(score)
                        filtered_docs.append(doc)
                        config.logger.debug(f"Document similarity score: {score}")
                    else:
                        config.logger.debug(f"Document filtered out due to low similarity: {score}")
                config.logger.info(f"Search completed in {time.time() - start_time:.4f}s, returning {len(filtered_docs)} documents")
                return filtered_docs

            candidate_docs = []
            for doc, score in docs_with_scores:
                if score >= similarity_threshold:
                    doc.metadata = dict(doc.metadata or {})
                    doc.metadata["score"] = float(score)
                    candidate_docs.append(doc)

            if not candidate_docs:
                config.logger.info(
                    f"Search completed in {time.time() - start_time:.4f}s, "
                    "returning 0 documents after similarity filtering"
                )
                return []

            # 使用Rerank进行重排序
            try:
                rerank_start = time.time()
                rerank_results = self.reranker.rerank(query, candidate_docs, top_k=k)
                rerank_time = time.time() - rerank_start
                config.logger.info(f"Rerank completed in {rerank_time:.4f}s, top {len(rerank_results)} results")

                # 提取重排序后的文档
                reranked_docs = [r.document for r in rerank_results]

                # Rerank已经按相关性排序，这里不再应用similarity_threshold
                # 但如果需要可以在这里添加额外的过滤逻辑
                config.logger.info(f"Search completed in {time.time() - start_time:.4f}s, returning {len(reranked_docs)} documents")

                return reranked_docs

            except Exception as rerank_error:
                config.logger.error(f"Rerank failed: {rerank_error}, falling back to vector search")
                # Rerank失败时，回退到原始的向量搜索结果
                filtered_docs = []
                for doc, score in docs_with_scores:
                    if score >= similarity_threshold:
                        doc.metadata = dict(doc.metadata or {})
                        doc.metadata["score"] = float(score)
                        filtered_docs.append(doc)
                config.logger.info(f"Search completed in {time.time() - start_time:.4f}s (Rerank failed, fallback to vector search), returning {len(filtered_docs)} documents")
                return filtered_docs

        except VectorIndexUnavailableError:
            raise
        except Exception as e:
            config.logger.error(f"Search error: {e}", exc_info=True)
            raise VectorIndexUnavailableError(f"向量检索失败: {e}") from e

    def delete_document(self, doc_id: int):
        """
        根据 doc_id 删除文档向量

        Milvus: 支持高效删除
        FAISS: 标记删除（实际需要重建索引）
        """
        health = self.get_health()
        if health["status"] == "UNAVAILABLE":
            raise VectorIndexUnavailableError(health["message"])

        if self.vector_store is None:
            config.logger.warning(f"No vector store available, cannot delete doc_id: {doc_id}")
            return

        if self.use_milvus:
            # Milvus删除逻辑
            try:
                config.logger.info(f"Deleting document with doc_id: {doc_id} from Milvus")

                # 构建删除表达式（使用类型转换确保安全性）
                if not isinstance(doc_id, int):
                    raise ValueError(f"doc_id must be an integer, got {type(doc_id)}")
                delete_expr = f'doc_id in [{doc_id}]'

                # 执行删除
                result = self.vector_store.delete(expr=delete_expr)
                config.logger.info(f"Milvus delete result: {result}")

                # 可选：压缩集合以释放空间
                # utility.compact(collection_name=self.collection_name)

                config.logger.info(f"Successfully deleted document {doc_id} from Milvus")

            except Exception as e:
                config.logger.error(f"Failed to delete document from Milvus: {e}")
                # 尝试其他删除方法
                self._delete_document_fallback(doc_id)

        else:
            # FAISS删除逻辑（效率较低）
            config.logger.info(f"Deleting document with doc_id: {doc_id} from FAISS")
            self._delete_document_faiss(doc_id)

    def _delete_document_fallback(self, doc_id: int):
        """备用删除方法：通过查询找到ID然后删除"""
        try:
            # 先搜索包含该doc_id的文档
            filter_dict = {"doc_id": doc_id}
            docs_to_delete = self.search("", k=1000, filter_dict=filter_dict)

            if not docs_to_delete:
                config.logger.info(f"No documents found with doc_id: {doc_id}")
                return

            # 提取文档ID（假设metadata中有唯一ID）
            ids_to_delete = []
            for doc in docs_to_delete:
                if 'chunk_id' in doc.metadata:
                    ids_to_delete.append(doc.metadata['chunk_id'])

            if ids_to_delete:
                # 执行删除
                self.vector_store.delete(ids=ids_to_delete)
                config.logger.info(f"Deleted {len(ids_to_delete)} chunks for doc_id {doc_id}")
            else:
                config.logger.info(f"No deletable chunks found for doc_id {doc_id}")

        except Exception as e:
            config.logger.error(f"Fallback delete failed: {e}")

    def _delete_document_faiss(self, doc_id: int):
        """FAISS删除实现（需要重建索引）"""
        try:
            # 找到所有 metadata['doc_id'] == doc_id 的 ID
            ids_to_delete = []
            for doc_uuid, doc in self.vector_store.docstore._dict.items():
                if doc.metadata.get('doc_id') == doc_id:
                    ids_to_delete.append(doc_uuid)

            if ids_to_delete:
                # FAISS的delete方法可能不彻底，这里尝试删除
                self.vector_store.delete(ids_to_delete)
                self._save_faiss()
                config.logger.info(f"Deleted {len(ids_to_delete)} chunks for doc_id {doc_id}")

                # 建议：定期重建FAISS索引以提高效率
                if len(ids_to_delete) > 100:
                    config.logger.warning("Large deletion in FAISS. Consider rebuilding index for better performance.")
            else:
                config.logger.info(f"No chunks found for doc_id {doc_id}")

        except Exception as e:
            config.logger.error(f"Failed to delete document from FAISS: {e}")

    def delete_collection(self):
        """
        删除整个向量库 (慎用)
        """
        if self.use_milvus:
            try:
                # 删除Milvus集合
                utility.drop_collection(self.collection_name)
                config.logger.info(f"Successfully deleted Milvus collection '{self.collection_name}'")
            except Exception as e:
                config.logger.error(f"Failed to delete Milvus collection: {e}")
        else:
            # 删除FAISS目录
            if os.path.exists(self.persist_directory):
                shutil.rmtree(self.persist_directory)
            self.vector_store = None
            config.logger.info("Successfully deleted FAISS collection")

    def get_stats(self) -> Dict[str, Any]:
        """获取向量库统计信息"""
        stats = {
            "using_milvus": self.use_milvus,
            "collection_name": self.collection_name if self.use_milvus else None,
            "persist_directory": self.persist_directory if not self.use_milvus else None,
            "health": self.get_health(),
        }

        if self.use_milvus and self.vector_store:
            try:
                # 获取Milvus集合信息
                collection_stats = utility.get_collection_stats(self.collection_name)
                stats.update({
                    "row_count": collection_stats.get("row_count", 0),
                    "partitions": collection_stats.get("partitions", []),
                })
            except Exception as e:
                stats["error"] = f"Failed to get Milvus stats: {e}"
        elif not self.use_milvus and self.vector_store:
            # FAISS统计
            stats["doc_count"] = len(self.vector_store.docstore._dict) if hasattr(self.vector_store, 'docstore') else 0

        return stats

    def migrate_faiss_to_milvus(self):
        """将FAISS数据迁移到Milvus"""
        if not self.use_milvus or self.vector_store is None:
            config.logger.warning("Cannot migrate: not using Milvus or no vector store")
            return False

        try:
            config.logger.info("Starting migration from FAISS to Milvus...")

            # 1. 加载FAISS数据
            if os.path.exists(self.persist_directory):
                faiss_store = FAISS.load_local(self.persist_directory, self.embeddings, allow_dangerous_deserialization=True)

                # 2. 提取所有文档
                all_docs = []
                for doc_uuid, doc in faiss_store.docstore._dict.items():
                    all_docs.append(doc)

                # 3. 添加到Milvus
                if all_docs:
                    self.add_documents(all_docs)
                    config.logger.info(f"Migrated {len(all_docs)} documents from FAISS to Milvus")

                    # 4. 备份原FAISS数据
                    backup_dir = self.persist_directory + "_migrated_backup"
                    if os.path.exists(backup_dir):
                        shutil.rmtree(backup_dir)
                    shutil.move(self.persist_directory, backup_dir)
                    config.logger.info(f"Backed up FAISS data to {backup_dir}")

                    return True

            return False

        except Exception as e:
            config.logger.error(f"Migration failed: {e}")
            return False


# 测试可以通过环境变量关闭全局实例，避免加载真实 embedding 模型和索引。
if os.getenv("VECTOR_STORE_DISABLE_GLOBAL_INIT", "false").lower() in {
    "1",
    "true",
    "yes",
}:
    vector_store_manager = None
else:
    vector_store_manager = VectorStoreManager()

# 导出（保持兼容性，同时保留完整管理器）
vector_store = vector_store_manager
