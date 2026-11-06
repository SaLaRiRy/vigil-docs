from langchain_core.documents import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.vector_index import VectorIndexUnavailableError
from workflows.knowledge_qa_agent import KnowledgeQAAgent


class SimpleRouter:
    def classify_complexity(self, question):
        return "simple"


class MediumRouter:
    def classify_complexity(self, question):
        return "medium"


class FailedRetrievalAgent:
    def retrieve(self, **kwargs):
        from workflows.retrieval_agent import RetrievalResult

        return RetrievalResult(
            original_query=kwargs["query"],
            success=False,
            error="向量索引不可用",
        )


class WorkingRetrievalAgent:
    def retrieve(self, **kwargs):
        from workflows.retrieval_agent import RetrievalResult

        document = {
            "content": "事务 ACID 包含原子性和一致性。",
            "metadata": {"doc_id": 46, "chunk_index": 1, "score": 0.58},
        }
        return RetrievalResult(
            original_query=kwargs["query"],
            retrieved_documents=[document],
            reranked_documents=[document],
            scores=[0.58],
            citations={
                "sources": [
                    {
                        "doc_id": 46,
                        "doc": "文档46",
                        "score": 0.58,
                    }
                ]
            },
            success=True,
        )


class FailingVectorStore:
    def search(self, **kwargs):
        raise VectorIndexUnavailableError("索引缺少 manifest")


class EmptyVectorStore:
    def search(self, **kwargs):
        return []


class WorkingVectorStore:
    def search(self, **kwargs):
        return [
            Document(
                page_content="事务 ACID 包含原子性、一致性、隔离性和持久性。",
                metadata={
                    "doc_id": 42,
                    "source": "数据库基础.pdf",
                    "chunk_index": 3,
                    "score": 0.92,
                },
            )
        ]


class RecordingLLM:
    def __init__(self):
        self.calls = 0

    def get_answer(self, question, context_docs, conversation_context=""):
        self.calls += 1
        return "不应调用 LLM"

    def get_answer_stream(self, **kwargs):
        self.calls += 1
        yield '{"type": "end", "content": "不应调用 LLM"}'


def test_index_unavailable_is_reported_without_llm_fallback():
    llm = RecordingLLM()
    agent = KnowledgeQAAgent(
        vector_store=FailingVectorStore(),
        llm_service=llm,
        router=SimpleRouter(),
    )

    result = agent.ask("事务 ACID 是什么")

    assert result["error"] is True
    assert result["error_code"] == "INDEX_UNAVAILABLE"
    assert result["sources"] == []
    assert llm.calls == 0


def test_healthy_no_match_does_not_call_llm():
    llm = RecordingLLM()
    agent = KnowledgeQAAgent(
        vector_store=EmptyVectorStore(),
        llm_service=llm,
        router=SimpleRouter(),
    )

    result = agent.ask("完全不存在的问题", context="之前聊天里提到过一些无关内容")

    assert result.get("error") is not True
    assert result["sources"] == []
    assert "知识库中没有找到" in result["answer"]
    assert llm.calls == 0


def test_answer_uses_retrieved_document_and_returns_citation():
    llm = RecordingLLM()
    agent = KnowledgeQAAgent(
        vector_store=WorkingVectorStore(),
        llm_service=llm,
        router=SimpleRouter(),
    )

    result = agent.ask("事务 ACID 是什么")

    assert result["answer"] == "不应调用 LLM"
    assert result["has_sources"] is True
    assert result["sources"] == [
        {
            "doc_id": 42,
            "doc": "数据库基础.pdf",
            "page": None,
            "chunk_index": 3,
            "score": 0.92,
        }
    ]
    assert llm.calls == 1


def test_retrieval_failure_is_not_reported_as_a_knowledge_base_no_match():
    llm = RecordingLLM()
    agent = KnowledgeQAAgent(
        vector_store=EmptyVectorStore(),
        llm_service=llm,
        retrieval_agent=FailedRetrievalAgent(),
        router=MediumRouter(),
    )

    result = agent.ask("请分析一下这个问题的上下文")

    assert result["error"] is True
    assert result["error_code"] == "INDEX_UNAVAILABLE"
    assert "没有找到" not in result["answer"]
    assert llm.calls == 0


def test_stream_reports_unavailable_index_without_llm_fallback():
    llm = RecordingLLM()
    agent = KnowledgeQAAgent(
        vector_store=FailingVectorStore(),
        llm_service=llm,
        router=SimpleRouter(),
    )

    events = list(agent.ask_stream("事务 ACID 是什么"))

    assert '"error_code": "INDEX_UNAVAILABLE"' in events[-1]
    assert llm.calls == 0


def test_medium_path_returns_document_citation_for_short_question():
    llm = RecordingLLM()
    agent = KnowledgeQAAgent(
        vector_store=EmptyVectorStore(),
        llm_service=llm,
        retrieval_agent=WorkingRetrievalAgent(),
        router=MediumRouter(),
    )

    result = agent.ask("事务ACID是什么")

    assert result["has_sources"] is True
    assert result["sources"][0]["doc_id"] == 46
    assert result["sources"][0]["score"] == 0.58
    assert llm.calls == 1


def test_question_api_exposes_an_unavailable_index_to_clients(monkeypatch):
    import api.routes as routes

    agent = KnowledgeQAAgent(
        vector_store=FailingVectorStore(),
        llm_service=RecordingLLM(),
        router=SimpleRouter(),
    )

    class UnavailableRouter:
        def route(self, **kwargs):
            return agent.ask(kwargs["input_text"])

    monkeypatch.setattr(routes, "router_agent", UnavailableRouter())
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    response = TestClient(app).post(
        "/api/ask",
        json={"question": "事务 ACID 是什么"},
    )

    assert response.status_code == 200
    assert response.json()["error"] is True
    assert response.json()["error_code"] == "INDEX_UNAVAILABLE"
    assert response.json()["sources"] == []


def _ask_api(agent, monkeypatch):
    import api.routes as routes

    class AgentRouter:
        def route(self, **kwargs):
            return agent.ask(kwargs["input_text"])

    monkeypatch.setattr(routes, "router_agent", AgentRouter())
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    return TestClient(app)


def test_question_api_returns_retrieved_source(monkeypatch):
    client = _ask_api(
        KnowledgeQAAgent(
            vector_store=WorkingVectorStore(),
            llm_service=RecordingLLM(),
            router=SimpleRouter(),
        ),
        monkeypatch,
    )

    response = client.post("/api/ask", json={"question": "事务 ACID 是什么"})

    assert response.status_code == 200
    assert response.json()["sources"][0]["doc_id"] == 42
    assert response.json()["has_sources"] is True
    assert response.json().get("error") is False


def test_question_api_reports_a_genuine_no_match(monkeypatch):
    client = _ask_api(
        KnowledgeQAAgent(
            vector_store=EmptyVectorStore(),
            llm_service=RecordingLLM(),
            router=SimpleRouter(),
        ),
        monkeypatch,
    )

    response = client.post("/api/ask", json={"question": "完全不存在的问题"})

    assert response.status_code == 200
    assert response.json()["sources"] == []
    assert "知识库中没有找到" in response.json()["answer"]
    assert response.json().get("error") is False
