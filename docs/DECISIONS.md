# Architecture Decision Records

This file uses a simple ADR format. New decisions must be appended as new records; historical ADRs must not be rewritten to conceal changed direction.

本文使用简单 ADR 格式。后续架构决策继续追加 `ADR-002`、`ADR-003` 等，不覆盖历史记录。

## ADR-001 - Do not introduce LangChain or LangGraph in the initial runtime

**Status:** Accepted

### Context

The project needs to understand the core Agent Runtime behavior before adopting a framework that may hide execution details.

中文释义：当前最重要的学习和工程目标，是看清上下文如何提交、工具调用如何产生、工具结果如何返回以及循环何时结束。若第一天就让框架封装这些细节，项目会失去对核心运行机制的直接理解。

### Decision

The initial Agent Runtime will use direct Python code and an LLM API. LangChain and LangGraph will be evaluated only when a concrete workflow-orchestration requirement exists.

中文释义：初始 Runtime 采用直接 Python + LLM API 的实现。未来如果出现明确的工作流状态、条件转移或编排复杂度问题，再以新的架构评估决定是否引入框架。

### Reason

* runtime behavior is more explicit
* testing is easier
* there are fewer hidden abstractions
* later framework adoption remains an explicit architectural decision

中文释义：这样做便于理解和 Review，也能让测试直接覆盖关键行为。代价是早期需要自行编写一部分基础协调代码，但这属于当前阶段可接受的成本。

### Consequences

**Positive:**

* easier to understand
* easier to test
* easier to review
* clearer dependency and failure boundaries

**Negative:**

* the project must write and maintain some custom foundational code initially
* framework conveniences are not available at the start

### Revisit Trigger

Revisit this decision when explicit workflow states and transitions create a demonstrated orchestration problem that a framework can solve without obscuring required runtime behavior.

## ADR-002 - Model Approval as a separate domain entity

**Status:** Accepted

### Context

An Approval represents a human decision for one protected ToolCall, while a Task represents the lifecycle of the overall Agent execution. Embedding approval state into `TaskStatus` would conflate two different domain concerns.

### Decision

Model `Approval` as an independent domain entity associated conceptually with a `Task` and a protected ToolCall. New entity creation and persistence rehydration use separate domain paths: new Approval instances start in `PENDING`, while historical states are restored through `Approval.restore(...)`.

### Consequences

* Task lifecycle and approval decision lifecycle remain independently explicit.
* A Task can conceptually have multiple Approval records.
* Approval persistence, API exposure, pause/resume, and post-approval Tool execution remain separate future capabilities.

### Revisit Trigger

Revisit this decision only if a demonstrated workflow or persistence requirement shows that the independent Approval boundary no longer represents the domain accurately.


## ADR-003 - Atomic persistence for the HITL pause

**Status:** Accepted; final Re-Review validated.

### Context

The first TASK-023 implementation committed Approval and Task WAITING separately. Independent Review rejected that design after PostgreSQL failure injection demonstrated a durable PENDING Approval with a RUNNING Task after execution had stopped. This revision replaces that proposal; it is not an accepted residual compromise.

### Decision

HITL pause durable state requires Approval(PENDING) and Task(WAITING_APPROVAL) in one atomic transaction. ProtectedToolExecutionService constructs an unpersisted Approval and raises ApprovalRequired with the entity and its existing identity fields. Runtime passes the signal unchanged and has no database dependency.

TaskExecutionService builds a waiting candidate through Task.restore and the domain transition. HITLPausePersistence owns a short transaction on one request-scoped Session: stage Approval, flush, stage Task WAITING, flush, commit once. The transaction starts only after the protected request is identified; it is never held across Agent/LLM execution. Standalone repository create/save still commit; explicit stage_create/stage_save leave transaction ownership to the coordinator.

### Consequences

- The API returns waiting_approval only after the atomic commit succeeds.
- A statement/commit failure rolls back both writes. The original RUNNING domain Task remains available for a legal FAILED transition and a separate best-effort save; the original exception propagates. A failed FAILED save does not guarantee durable FAILED.
- Rollback failure invalidates the Session connection and preserves the original persistence exception; no Tool fallback is allowed.
- PostgreSQL INSERT, WAITING UPDATE, and deferred-trigger COMMIT failures are formal regressions, alongside commit counting and pre/post-commit visibility checks.
- A lost commit acknowledgement may raise after PostgreSQL has committed the pause. Generic execution failure handling therefore persists a valid FAILED candidate through a single conditional UPDATE WHERE id matches AND status = RUNNING. A rowcount of zero conveys no confirmed replacement state; the original exception still propagates. This protects committed WAITING_APPROVAL without read-then-write or reconciliation. Real PostgreSQL commit followed by simulated OperationalError is covered at both Service and API boundaries.
- No resume, checkpoint, decision API, or approved execution is implemented.

### Revisit Trigger

Revisit recovery for unknown transaction outcomes and checkpoint storage when resume or reconciliation is explicitly scoped.
