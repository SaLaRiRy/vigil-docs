# Secure async processing and approval demo

中文功能清单、原项目改动和范围边界见
[二次开发工作总结](mvp-implementation-summary.md)。

本次 MVP 使用本机 RabbitMQ/MySQL/Redis，不要求 Docker。下面的 Docker 说明若出现在
项目旧 README 中，仅属于原项目启动方式，不是本功能链路的验收前置条件。

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

用户可见入口：

- 用户知识库：`http://127.0.0.1:3000/knowledge`
- 管理员审批中心：`http://127.0.0.1:3000/admin/approvals`

原项目的普通问答、聊天、仪表盘、用户管理、问答日志、Agent 执行记录、知识巡检和自动报表
页面继续保留；本次新增逻辑只作用于文档处理与删除审批链路。
