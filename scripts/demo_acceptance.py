import json
import os
import queue
import random
import sys
import threading
import time
from pathlib import Path

import pika
import redis
import requests


FIXTURES = Path(__file__).resolve().parent / "fixtures"
JAVA = os.getenv("JAVA_BASE_URL", "http://127.0.0.1:8080")
PYTHON = os.getenv("PYTHON_BASE_URL", "http://127.0.0.1:8000")


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def api(method, path, token=None, **kwargs):
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.request(method, f"{JAVA}{path}", headers=headers, timeout=180, **kwargs)
    response.raise_for_status()
    payload = response.json()
    check(payload.get("code") == 200, f"{method} {path} failed: {payload}")
    return payload["data"]


def register_fixture_user():
    phone = f"139{random.randint(10000000, 99999999)}"
    api("POST", "/api/auth/sendCode", params={"phone": phone})
    client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    code = client.get(f"sms:code:{phone}")
    check(code is not None, "SMS fixture code was not written to Redis")
    return api(
        "POST",
        "/api/auth/register",
        json={
            "phone": phone,
            "code": code,
            "password": "demo-pass-123",
            "username": f"demo_{phone[-4:]}",
        },
    )["accessToken"]


def upload(token, filename):
    with (FIXTURES / filename).open("rb") as fixture:
        response = requests.post(
            f"{JAVA}/api/knowledge/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (filename, fixture)},
            timeout=180,
        )
    response.raise_for_status()
    payload = response.json()
    check(payload.get("code") == 200, payload)
    return payload["data"]


def wait_status(token, document_id, expected, timeout=90):
    deadline = time.time() + timeout
    latest = None
    while time.time() < deadline:
        documents = api("GET", "/api/knowledge/list", token=token)
        latest = next((document for document in documents if document["id"] == document_id), None)
        if latest and latest["status"] in expected:
            return latest
        time.sleep(1)
    raise AssertionError(f"Document {document_id} did not reach {expected}; latest={latest}")


def queue_depth(queue):
    credentials = pika.PlainCredentials(
        os.getenv("RABBITMQ_USERNAME", "guest"),
        os.getenv("RABBITMQ_PASSWORD", "guest"),
    )
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            os.getenv("RABBITMQ_HOST", "localhost"),
            int(os.getenv("RABBITMQ_PORT", "5672")),
            credentials=credentials,
        )
    )
    channel = connection.channel()
    result = channel.queue_declare(queue=queue, durable=True, passive=True)
    connection.close()
    return result.method.message_count


def start_sse_listener(admin_token):
    events = queue.Queue()

    def listen():
        try:
            response = requests.get(
                f"{JAVA}/api/admin/approvals/stream",
                headers={"Authorization": f"Bearer {admin_token}"},
                stream=True,
                timeout=(10, 90),
            )
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if line and line.startswith("data:"):
                    events.put(json.loads(line[5:].strip()))
        except Exception as exc:
            events.put({"streamError": str(exc)})

    threading.Thread(target=listen, daemon=True).start()
    return events


def wait_for_sse_approval(events, approval_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            event = events.get(timeout=max(0.1, deadline - time.time()))
        except queue.Empty:
            break
        if event.get("approvalId") == approval_id:
            return event
        if event.get("streamError"):
            raise AssertionError(event["streamError"])
    raise AssertionError("Pending approval was not delivered over SSE")


def main():
    if not os.getenv("DASHSCOPE_API_KEY"):
        raise SystemExit("DASHSCOPE_API_KEY is required for valid-document vectorization")

    requests.get(f"{PYTHON}/health", timeout=10).raise_for_status()
    user_token = register_fixture_user()
    admin_login = requests.post(
        f"{JAVA}/api/admin/login",
        data={"username": "admin", "password": "admin123"},
        timeout=30,
    ).json()
    check(admin_login.get("code") == 200, admin_login)
    admin_token = admin_login["data"]["accessToken"]

    valid = upload(user_token, "valid-document.txt")
    completed = wait_status(user_token, valid["id"], {"COMPLETED"}, timeout=180)
    print(json.dumps({"scenario": "valid_document", "document": completed}, ensure_ascii=False))

    malformed = upload(user_token, "malformed-document.pdf")
    failed = wait_status(user_token, malformed["id"], {"FAILED"}, timeout=90)
    check(queue_depth("agentcraft.document.dlq.v1") >= 1, "Malformed document did not reach the DLQ")
    print(json.dumps({"scenario": "malformed_retry_dlq", "document": failed}, ensure_ascii=False))

    refusal = api(
        "POST",
        f"/api/knowledge/{valid['id']}/deletion-request",
        token=user_token,
        json={"instruction": (FIXTURES / "prompt-injection.txt").read_text(encoding="utf-8")},
    )
    check(refusal["state"] == "REFUSED", "Prompt injection was not refused")
    print(json.dumps({"scenario": "prompt_injection_refused", "result": refusal}, ensure_ascii=False))

    sse_events = start_sse_listener(admin_token)
    time.sleep(0.5)
    approval = api(
        "POST",
        f"/api/knowledge/{valid['id']}/deletion-request",
        token=user_token,
        json={"instruction": "Delete the explicitly selected document"},
    )
    wait_for_sse_approval(sse_events, approval["approvalId"])
    pending = api("GET", "/api/admin/approvals/pending", token=admin_token)
    check(any(item["id"] == approval["approvalId"] for item in pending), "Approval center omitted pending request")
    decision = api(
        "POST",
        f"/api/admin/approvals/{approval['approvalId']}/decision",
        token=admin_token,
        json={"decision": "APPROVE", "comment": "Acceptance approval"},
    )
    duplicate = api(
        "POST",
        f"/api/admin/approvals/{approval['approvalId']}/decision",
        token=admin_token,
        json={"decision": "APPROVE", "comment": "Duplicate click"},
    )
    check(duplicate["idempotentReplay"] is True, "Duplicate approval was not idempotent")
    deleted = wait_status(user_token, valid["id"], {"DELETED"}, timeout=90)
    audit = api("GET", f"/api/admin/approvals/{approval['approvalId']}/audit", token=admin_token)
    tool_calls = api("GET", f"/api/agent-run/{approval['runId']}/tool-calls", token=user_token)
    check(len(tool_calls) == 1, "Approved deletion did not execute exactly once")
    print(json.dumps({
        "scenario": "approved_deletion",
        "decision": decision,
        "document": deleted,
        "auditEvents": [event["eventType"] for event in audit],
        "toolCalls": tool_calls,
    }, ensure_ascii=False))

    reject_target = upload(user_token, "valid-document.txt")
    wait_status(user_token, reject_target["id"], {"COMPLETED"}, timeout=180)
    rejection = api(
        "POST",
        f"/api/knowledge/{reject_target['id']}/deletion-request",
        token=user_token,
        json={"instruction": "Delete the explicitly selected document"},
    )
    api(
        "POST",
        f"/api/admin/approvals/{rejection['approvalId']}/decision",
        token=admin_token,
        json={"decision": "REJECT", "comment": "Acceptance rejection"},
    )
    still_present = wait_status(user_token, reject_target["id"], {"COMPLETED"}, timeout=15)
    check(still_present["status"] == "COMPLETED", "Rejected deletion changed the document")
    print(json.dumps({"scenario": "rejection", "document": still_present}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ACCEPTANCE FAILED: {exc}", file=sys.stderr)
        raise
