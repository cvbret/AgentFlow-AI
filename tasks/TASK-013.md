# TASK-013 - Task Status Filtering
# TASK-013：Task 状态筛选

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
- tasks/TASK-012.md

重点读取：

- backend/app/api/tasks.py
- backend/app/tasks/repository.py
- backend/app/tasks/models.py
- backend/app/db/models/task.py
- backend/tests/test_task_api.py
- backend/tests/test_task_repository.py

Repository 是 Source of Truth。

---

## 2. Planned Write Set

第一次写操作前报告 Planned Write Set。

预计主要修改：

- tasks/TASK-013.md
- backend/app/tasks/repository.py
- backend/app/api/tasks.py
- backend/tests/test_task_repository.py
- backend/tests/test_task_api.py

如确实需要其他文件，先说明原因。

---

# 3. Goal

扩展现有：

GET /api/tasks

增加可选：

status

例如：

GET /api/tasks?status=failed

仍支持：

limit
offset

---

# 4. Supported Status Values

只允许：

pending
running
succeeded
failed

优先直接使用现有 TaskStatus Enum 作为 FastAPI query parameter 类型。

非法值例如：

GET /api/tasks?status=unknown

应返回：

422

不要手工解析字符串。

---

# 5. Optional Filter

status 必须是 optional。

也就是说：

GET /api/tasks

仍然表示：

查询全部 Task。

不能破坏 TASK-012 contract。

---

# 6. Repository Contract

扩展 TaskRepository.list(...)。

推荐：

list(
    limit: int,
    offset: int,
    status: TaskStatus | None = None,
) -> list[Task]

或符合当前项目风格的等价接口。

要求：

如果 status is None：

不加 WHERE status 条件。

如果 status 有值：

在 SQL 层执行：

WHERE status = ...

不要：

- 查询全部后 Python filter
- API 自己 filter

---

# 7. Query Order

正确逻辑应为：

WHERE status = ?
↓
ORDER BY created_at DESC, id DESC
↓
LIMIT
↓
OFFSET

重点：

filter 必须发生在 pagination 之前。

不要先分页再筛选。

---

# 8. Deterministic Ordering

继续保持 TASK-012：

created_at DESC, id DESC

status filter 不得破坏稳定排序。

---

# 9. API Boundary

正确结构：

HTTP
↓
Task API
↓
TaskRepository.list(
    limit,
    offset,
    status,
)
↓
list[Domain Task]
↓
TaskListResponse

API 不直接：

- query TaskRecord
- filter ORM rows
- Python filter list

---

# 10. Response Contract

继续保持：

{
  "items": [...],
  "limit": 20,
  "offset": 0
}

不要求在 response 中增加：

status

不要改变现有 response schema。

---

# 11. Empty Filter Result

例如：

GET /api/tasks?status=failed

如果没有 FAILED Task：

HTTP 200

返回：

{
  "items": [],
  "limit": 20,
  "offset": 0
}

不要返回 404。

---

# 12. Repository Tests

至少覆盖：

### Test A
status=None
→ 返回全部状态

### Test B
status=FAILED
→ 只返回 FAILED

### Test C
status=SUCCEEDED
→ 只返回 SUCCEEDED

### Test D
filter + limit

确认 limit 在过滤结果上生效。

### Test E
filter + offset

确认 offset 在过滤结果上生效。

### Test F
filter 后 ordering

仍然：

created_at DESC, id DESC

---

# 13. API Tests

至少覆盖：

### Test 1
GET /api/tasks
→ 不传 status
→ 保持原行为

### Test 2
?status=failed
→ Repository 收到 TaskStatus.FAILED

### Test 3
?status=succeeded
→ 正确筛选

### Test 4
?status=unknown
→ 422

### Test 5
status + limit + offset

例如：

?status=failed&limit=2&offset=1

正确传递。

### Test 6
empty filtered result
→ 200 + items=[]

---

# 14. PostgreSQL Integration

增加真实 PostgreSQL integration test。

至少：

1. 创建多个不同状态 Task
2. 保存 PostgreSQL
3. GET /api/tasks?status=failed
4. 确认只返回 FAILED
5. GET /api/tasks?status=succeeded
6. 确认只返回 SUCCEEDED
7. 验证 limit/offset 在过滤后正确生效
8. 验证排序仍为 deterministic

不要只用 Fake Repository 宣称完成。

---

# 15. Enum Mapping

重点确认：

Domain：

TaskStatus.FAILED

ORM：

status 字段当前实际存储方式

API：

"failed"

三层映射一致。

不要引入新的第二套 status enum。

---

# 16. Existing API Regression

确认：

GET /api/tasks/{task_id}

继续：

200 / 404 / 422

以及：

GET /api/tasks

不传 status 时继续保持 TASK-012 行为。

---

# 17. Agent Run Regression

确认：

POST /api/agent/run

继续返回：

{
  "task_id": "...",
  "answer": "..."
}

不要修改 TASK-011 contract。

---

# 18. Security

status filter 不得引入：

- raw SQL string interpolation
- credentials exposure
- traceback exposure

必须继续使用 SQLAlchemy 表达式构造查询。

不要手写 SQL 字符串拼接 status。

---

# 19. Do Not Add

不要实现：

- status 多选
- status=failed,succeeded
- search
- date filters
- sort parameter
- total count
- cursor pagination
- query DSL
- Specification Pattern
- Generic Filter system
- Redis
- cache
- queue
- worker
- observability
- TASK-014

---

# 20. Tests

执行：

python -m pytest -ra

有 PostgreSQL 环境时执行真实 integration tests。

所有历史测试必须继续通过。

---

# 21. Post-write Audit

执行：

git status --short --branch --untracked-files=all
git diff --check

比较：

Planned Write Set
vs
Actual Repository Changes

---

# 22. 不要 State Sync

不要修改：

docs/CURRENT_STATE.md
docs/AI_HANDOFF.md

---

# 23. 不要 Commit / Push

不要：

git add
git commit
git push

---

# 24. Completion Report

## Planned Write Set

## Actual Repository Changes

## Status Filter Contract

说明：

status optional
allowed values

## Repository Query

说明：

WHERE
ORDER BY
LIMIT/OFFSET

执行顺序。

## API Contract

## Enum Mapping

## Pagination Interaction

## Empty Result Behavior

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

- TASK-013 only
- single status filter only
- no multi-status
- no search
- no custom sorting
- no TASK-014
- no State Sync
- no commit / push
