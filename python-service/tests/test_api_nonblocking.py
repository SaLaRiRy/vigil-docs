import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi import FastAPI
from fastapi.testclient import TestClient


class SlowRouter:
    def __init__(self):
        self.started = Event()

    def route(self, **kwargs):
        self.started.set()
        time.sleep(0.8)
        return {
            "answer": "ok",
            "sources": [],
            "task_type": "knowledge_qa",
        }


class HealthyVectorStore:
    def get_health(self):
        return {
            "status": "HEALTHY",
            "message": "index is healthy",
        }


def test_health_stays_responsive_while_ask_is_running(monkeypatch):
    import api.routes as routes

    slow_router = SlowRouter()
    monkeypatch.setattr(routes, "router_agent", slow_router)
    monkeypatch.setattr(routes, "vector_store", HealthyVectorStore())

    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=1) as executor:
            ask_future = executor.submit(
                client.post,
                "/api/ask",
                json={"question": "正在处理的问题"},
            )
            assert slow_router.started.wait(timeout=1)

            started = time.perf_counter()
            response = client.get("/api/health")
            elapsed = time.perf_counter() - started

            assert response.status_code == 200
            assert elapsed < 0.4
            assert ask_future.result(timeout=2).status_code == 200
