# Secure async processing and approval demo

## Start the local stack

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

The script validates MySQL, Redis, and RabbitMQ, starts the Python API, Python consumer,
Java backend, and React frontend when they are not already listening, and fails loudly if
readiness does not arrive. Runtime logs are written to `.runtime/`.

## Run the fixed acceptance flow

```powershell
python-service\.venv\Scripts\python.exe .\scripts\demo_acceptance.py
```

The flow creates a local fixture user and exercises:

1. A valid document moving to `COMPLETED`.
2. A malformed PDF being retried three times and reaching the DLQ and `FAILED`.
3. An obvious prompt-injection instruction being refused and audited.
4. An explicit deletion request reaching the administrator approval center.
5. Approval, duplicate decision replay, soft deletion, exactly-once tool execution, and cleanup audit.
6. Rejection leaving the selected document intact.

The approval center is available at `/admin/approvals` after administrator login. It reloads
authoritative state from MySQL and refreshes on SSE notifications.
