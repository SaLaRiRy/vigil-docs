from tools.citation import CitationIntegrator


def test_citation_sources_expose_the_knowledge_qa_contract():
    result = CitationIntegrator().integrate(
        answer="",
        documents=[
            {
                "content": "事务 ACID 包含原子性和一致性。",
                "metadata": {
                    "doc_id": 46,
                    "chunk_id": 460,
                    "chunk_index": 1,
                },
            }
        ],
        scores=[0.58],
        query="事务 ACID 是什么",
    )

    assert result["sources"][0]["doc_id"] == 46
    assert result["sources"][0]["doc"] == "文档46"
    assert result["sources"][0]["score"] == 0.58
