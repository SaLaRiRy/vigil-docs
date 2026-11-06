from langchain_core.documents import Document

import rebuild_index
from core.reindex import rebuild_index as build_index
from tests.test_vector_store import FixedEmbeddings


class FakeSource:
    def get_active_chunks(self):
        return [
            Document(
                page_content="事务 ACID 与一致性",
                metadata={
                    "doc_id": 1,
                    "chunk_id": 10,
                    "chunk_index": 0,
                    "source": "database.txt",
                },
            )
        ]

    def get_orphan_report(self):
        return {91: 2}

    def get_duplicate_report(self):
        return []


def test_dry_run_emits_machine_readable_target_manifest(tmp_path):
    report = build_index(
        source=FakeSource(),
        embeddings=FixedEmbeddings(dimension=8),
        target_dir=tmp_path / "faiss_index",
        apply=False,
        embedding_provider="local",
        embedding_model="fake-model",
    )

    assert report["status"] == "planned"
    assert report["target_manifest"] == {
        "schema_version": 1,
        "embedding_provider": "local",
        "embedding_model": "fake-model",
        "embedding_dimension": 8,
        "document_count": 1,
        "chunk_count": 1,
        "source_policy": "active_completed",
    }


def test_cli_defaults_to_non_destructive_dry_run(tmp_path, monkeypatch):
    captured = {}

    monkeypatch.setattr(
        rebuild_index,
        "create_embeddings",
        lambda: (FixedEmbeddings(dimension=8), "local", "fake-model"),
    )

    def fake_rebuild(*args, **kwargs):
        captured.update(kwargs)
        return {"mode": kwargs["apply"] and "apply" or "dry-run"}

    monkeypatch.setattr(rebuild_index, "rebuild_from_mysql", fake_rebuild)

    assert rebuild_index.main(["--index-dir", str(tmp_path / "faiss_index")]) == 0
    assert captured["apply"] is False
