# TASK-012 - Task Listing API
# TASK-012：Task 列表查询接口

你现在作为 AgentFlow-AI 项目的 Developer Agent 工作。

Repository root：

E:\AIProjects\AgentFlow-AI

所有分析、说明和 Completion Report 使用中文。

代码、命令、路径、类名、函数名和必要英文工程术语可以保留英文。

---

## 0. Workspace Verification

执行：

Get-Location
git rev-parse --show-toplevel
git status
git log --oneline -6

必须确认：

Repository root：
E:\AIProjects\AgentFlow-AI

Working tree：
clean

否则 STOP 并报告。

---

## 1. 开始前读取

读取：

- AGENTS.md
- docs/PROJECT.md
- docs/CURRENT_STATE.md
- docs/AI_HANDOFF.md
- docs/ARCHITECTURE.md
- docs/TECH_DEBT.md
- tasks/TASK-011.md

重点读取：

- backend/app/api/tasks.py
- backend/app/tasks/repository.py
- backend/app/tasks/models.py
- backend/app/db/models/task.py
- backend/app/api/dependencies.py
- backend/tests/test_task_api.py
- backend/tests/test_task_repository.py

Repository 是 Source of Truth。

---

## 2. Planned Write Set

第一次写操作前报告 Planned Write Set。

预计主要修改：

- tasks/TASK-012.md
- backend/app/tasks/repository.py
- backend/app/api/tasks.py
- backend/tests/test_task_repository.py
- backend/tests/test_task_api.py

如确实需要其他文件，先说明原因。

---

# 3. Goal

实现：

GET /api/tasks

支持最小 offset pagination：

- limit
- offset

默认：

limit = 20
offset = 0

---

# 4. Response Contract

建议：

GET /api/tasks

返回：

{
  "items": [
    {
      "id": "...",
      "status": "succeeded",
      "input": "...",
      "result": "...",
      "error": null,
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "limit": 20,
  "offset": 0
}

不要增加 total。

TASK-012 不要求 COUNT(*)。

---

# 5. Query Parameters

实现：

limit
offset

建议约束：

limit:
1 <= limit <= 100

offset:
offset >= 0

非法参数由 FastAPI/Pydantic 返回：

422

不要手工拼接 400。

---

# 6. Ordering

Repository list 必须具有稳定排序。

默认：

created_at DESC

为了避免多个 Task created_at 相同时顺序不稳定，
增加稳定 tie-breaker：

id DESC 或其他稳定唯一字段。

例如：

ORDER BY created_at DESC, id DESC

具体 SQLAlchemy 写法按当前 ORM 实现决定。

重点：

分页排序必须 deterministic。

---

# 7. Repository Contract

在 TaskRepository 增加最小列表能力，例如：

list(limit: int, offset: int) -> list[Task]

或符合当前项目命名风格的等价接口。

要求：

- 使用 ORM query
- limit
- offset
- deterministic ordering
- 返回 Domain Task
- 不返回 TaskRecord

不要建立 GenericRepository。

---

# 8. Domain Rehydration

所有查询到的 ORM TaskRecord：

必须通过现有受控 Domain rehydration 路径转换为 Task。

不要：

- model_construct()
- 直接返回 ORM
- 绕过现有 Task.restore()

---

# 9. API Boundary

正确结构：

HTTP
↓
Task API
↓
TaskRepository.list(...)
↓
list[Domain Task]
↓
List Response DTO

API 不直接写：

select(TaskRecord)

---

# 10. DTO Reuse

单个 item 尽量复用当前：

TaskQueryResponse

不要创建字段完全重复的第二套 Task DTO。

可以新增：

TaskListResponse

例如：

class TaskListResponse(BaseModel):
    items: list[TaskQueryResponse]
    limit: int
    offset: int

不要引入 generic pagination framework。

---

# 11. Empty Result

没有 Task 时：

HTTP 200

返回：

{
  "items": [],
  "limit": 20,
  "offset": 0
}

不要返回：

404

列表为空不是错误。

---

# 12. Repository Tests

至少覆盖：

### Test A
没有 Task：
返回 []

### Test B
多个 Task：
返回正确数量

### Test C
limit 生效

### Test D
offset 生效

### Test E
ordering：
最新 Task 在前

### Test F
分页无明显重复

使用 deterministic timestamps 或其他稳定方式构造测试。

---

# 13. API Tests

至少覆盖：

### Test 1
GET /api/tasks
默认 limit=20 offset=0

### Test 2
空列表：
200 + items=[]

### Test 3
自定义：

?limit=2&offset=1

正确传递给 Repository。

### Test 4
limit=0
→ 422

### Test 5
limit=101
→ 422

### Test 6
offset=-1
→ 422

### Test 7
Response items 使用 TaskQueryResponse contract

确认：

- status
- UUID
- timestamps
- result/error

---

# 14. PostgreSQL Integration

增加真实 PostgreSQL integration test。

至少：

1. 创建 3 个 Task
2. 持久化 PostgreSQL
3. GET /api/tasks?limit=2&offset=0
4. 验证只返回 2 个
5. GET /api/tasks?limit=2&offset=2
6. 验证下一页
7. 验证排序稳定

不要只通过 Fake Repository 测分页。

---

# 15. Ordering Test

分页的测试必须验证：

Task A
Task B
Task C

按照约定：

created_at DESC
+
stable tie-breaker

返回顺序确定。

不要只测试 set 相等。

---

# 16. Session Lifecycle

继续复用 request-scoped Session。

不要：

- process-global Session
- Repository 自己 close Session

---

# 17. Existing Single Query Regression

确认：

GET /api/tasks/{task_id}

继续：

- 200
- 404
- 422

不能因为添加：

GET /api/tasks

造成路由冲突。

---

# 18. Agent Run Regression

确认：

POST /api/agent/run

仍返回：

{
  "task_id": "...",
  "answer": "..."
}

不要修改 TASK-011 contract。

---

# 19. Security

列表响应不得包含：

- DATABASE_URL
- ORM object
- credentials
- provider secret
- internal Session data
- traceback

FAILED Task.error 继续使用既有安全描述。

---

# 20. Database Failure

如果 Repository list 查询抛数据库异常：

沿用当前全局安全 500 policy。

不要在 TASK-012 引入新的 DB exception framework。

---

# 21. Do Not Add

不要实现：

- total count
- status filter
- search
- custom ordering
- date filters
- cursor pagination
- page/page_size abstraction
- Redis
- cache
- queue
- worker
- cancellation
- observability
- LangGraph
- Multi-Agent
- TASK-013

---

# 22. Tests

执行：

python -m pytest -ra

有 PostgreSQL 环境时执行真实 integration tests。

历史测试必须继续通过。

---

# 23. Post-write Audit

执行：

git status --short --branch --untracked-files=all
git diff --check

比较：

Planned Write Set
vs
Actual Repository Changes

---

# 24. 不要 State Sync

不要修改：

docs/CURRENT_STATE.md
docs/AI_HANDOFF.md

---

# 25. 不要 Commit / Push

不要：

git add
git commit
git push

---

# 26. Completion Report

## Planned Write Set

## Actual Repository Changes

## Repository List Contract

说明：

limit
offset
ordering

## API Contract

说明：

GET /api/tasks

## Pagination

说明默认值和 validation。

## Ordering

说明 deterministic ordering。

## DTO Boundary

## Empty List Behavior

## PostgreSQL Integration

## Tests Added

## Tests Executed

## Test Results

## Regression Check

## Security Review

## Remaining Risks

## Technical Debt Introduced

## Workspace Boundary Verification

## Scope Verification

确认：

- TASK-012 only
- list API only
- offset pagination only
- no total count
- no filter
- no search
- no cursor pagination
- no TASK-013
- no State Sync
- no commit / push
