import requeue_document


class FakeVectorStore:
    def get_health(self):
        return {"status": "HEALTHY", "message": "index is ready"}


def test_requeue_cli_uses_an_initialized_vector_store(monkeypatch, capsys):
    captured = {}
    monkeypatch.setattr(
        requeue_document,
        "create_embeddings",
        lambda: (object(), "local", "fake-model"),
    )
    monkeypatch.setattr(
        requeue_document,
        "VectorStoreManager",
        lambda **kwargs: FakeVectorStore(),
    )

    def fake_recover(**kwargs):
        captured.update(kwargs)
        return {"status": "would_requeue"}

    monkeypatch.setattr(requeue_document, "recover_pending_document", fake_recover)

    assert requeue_document.main(["--doc-id", "62"]) == 0
    assert captured["index_health"]["status"] == "HEALTHY"
    assert captured["document_id"] == 62
    assert captured["apply"] is False
    assert '"would_requeue"' in capsys.readouterr().out
