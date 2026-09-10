# AgentFlow-AI 简历材料

## One-line Project Summary

基于 FastAPI、PostgreSQL 与 LangGraph 构建可靠任务执行后端，支持 Tool 安全边界、人工审批、跨进程继续执行和基于持久化证据的恢复。

## Resume Version - Compact

- 构建有界 Agent Tool Calling 链路，以 AgentRuntime façade 对接 LangGraph，保留自研 Task/Approval Domain、LLM 可靠性策略和应用服务边界。
- 实现 fail-closed Tool policy、checkpoint-first HITL、原子审批 continuation claim 与 fresh Runtime/Saver 恢复，覆盖 approve/reject 及跨请求流程。
- 通过 Execution Ledger、稳定 idempotency key、成功结果缓存与 generation fencing，约束重复执行和旧执行者覆盖；对不安全的 UNKNOWN 保持 RECOVERY_REQUIRED。
- 建立 18 类脱敏生命周期事件，以及单元、真实 PostgreSQL、并发、故障注入和 E2E 测试；正式全量基线 440 passed，0 failed/skipped/warnings。
- 完成非 root Docker 交付、双 schema 初始化和 GitHub Actions 验证；Container Delivery、CI Automation 已 Qualified，GitHub-hosted CI Run PASS。

## Resume Version - Detailed

**项目：AgentFlow-AI｜可靠 Agent Runtime 后端**

**问题与目标：** 多步 Tool 执行需要处理授权、进程重启和不确定副作用，单次对话成功不足以证明任务执行正确。项目围绕可持久化 Task 建立执行、暂停、继续和故障处置的闭环。

**核心工作：**

1. 明确 API → Application Services → AgentRuntime → LangGraph/LLM/Tool 的职责边界。LangGraph 提供状态编排与 interrupt/resume；自研层保留业务领域、安全策略、幂等策略、恢复判断和可观测语义。
2. 使用 PostgreSQL、SQLAlchemy 与 Alembic 管理 Task/Approval/Execution Ledger；通过短事务、唯一约束和条件更新协调暂停、审批竞争与执行 claim。checkpoint 表由 PostgresSaver 独立管理。
3. 在受保护执行中保存独立 execution UUID 与稳定 key，复用 SUCCEEDED 结果；在 stale EXECUTING/UNKNOWN 场景按 Tool capability 和新鲜持久化证据决定恢复或停止。
4. 为 LLM 实现 timeout、retryable classification、bounded retry、指数 backoff 与 jitter；为 Task/执行结果写入增加 generation fencing，处理提交确认丢失与旧执行者竞态。
5. 通过 ContextVar 请求隔离、关联 ID 和属性 allowlist 输出 18 类 JSON 生命周期事件；日志故障不改变业务语义，敏感正文不进入默认事件。
6. 将工程验证固化为 Docker/Compose 与 GitHub Actions：数据库 ready、业务 migration、checkpoint setup、全量门禁、镜像构建；正式基线 440 项全部通过。

**可验证产出：** [项目主页](../README.md)、[测试目录](../backend/tests)、[CI workflow](../.github/workflows/ci.yml)、[设计决策](DECISIONS.md)。当前结果来自 [CURRENT_STATE](CURRENT_STATE.md) 的 Reviewer/CI 事实，非本轮重新跑测。

**边界：** 未完成生产部署和真实 provider 生产验收；未接入真实业务流量，不填写未经测量的吞吐量、延迟收益、用户数或成本节省。无法承诺 universal exactly-once。默认 Tool 为 Calculator，受保护外部操作通过受控实现验证。

## Technical Keywords

Python 3.11 · FastAPI · PostgreSQL 17 · SQLAlchemy · Alembic · LangGraph · PostgresSaver · Pydantic · httpx · pytest · Docker Compose · GitHub Actions · HITL · Durable Workflow · Execution Ledger · Idempotency · Recovery / Reconciliation · Conditional Update · Generation Fencing · Structured Observability

## Interview Value

建议讲清三个具体场景：

- 审批后重建 Runtime，如何从保存的游标继续，而不是重跑整个任务。
- Tool 已成功但本地确认丢失时，为什么先查 Ledger/Checkpoint，而不是盲目 retry。
- 两个恢复请求竞争时，数据库 claim 和 generation fencing 分别保护什么，以及它们无法保护什么。

这是展示工程推理和故障边界的材料，不应包装成线上大规模生产实践。项目采用 AI-assisted workflow；面试时按实际参与情况说明自己的设计、实现、验证与 AI 协作职责，不把生成的 bullet 自动等同于个人独立完成证明。
