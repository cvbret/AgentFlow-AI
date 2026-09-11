# AgentFlow-AI Final Project Report

本报告总结当前已实现、已验证的后端能力，作为项目展示与技术交接入口。TASK-034 Final Project Packaging 与后续 Real LLM HTTP E2E Integration 均已通过 Independent Review；本报告不将未验证的部署或生产级 provider 能力表述为已完成。

## Project Goal

建立有界、可查询、可审批、可恢复的 Agent 任务执行链。重点解决模型调用可靠性、Tool 副作用授权、跨进程状态丢失和执行结果不确定，而不是仅返回一次聊天回答。

## Final Architecture

`FastAPI → Task/Application Services → AgentRuntime façade → LangGraph → LLM / Tool subsystem`

Task、Approval 与 Execution Ledger 由自研领域和 Repository 管理；PostgreSQL 是业务事实来源，Alembic 管业务 schema。LangGraph 承担图编排和状态推进，PostgresSaver 管 checkpoint schema。两套 schema 可以同库部署，但不存在跨业务提交、checkpoint 与外部效果的统一原子事务。

当前概览与三张 Mermaid 图见 [README](../README.md)。[ARCHITECTURE](ARCHITECTURE.md) 与 [DECISIONS](DECISIONS.md) 提供细节和历史决策；阅读历史阶段文字时应结合 [CURRENT_STATE](CURRENT_STATE.md) 的最新事实。

## Completed Capabilities

已实现 Agent Tool Calling、有界循环、Task 持久化与查询、LLM 可靠性策略、Tool safety、独立 Approval、HITL approve/reject、durable checkpoint、fresh Runtime/Saver 继续执行、Execution Ledger、成功结果重用、operator-triggered recovery 和结构化 observability。OpenAI-compatible LLM、真实 DeepSeek Tool Calling、AgentRuntime + LangGraph、FastAPI HTTP 与 PostgreSQL Task persistence 闭环已在开发环境完成验证。Docker 与 CI 已 Qualified。逐项状态与实现定位见 README Capability Matrix。

默认 Tool 为 Calculator；受保护 Tool 和 provider 使用受控实现验证。项目没有生产审批 UI、真实外部副作用业务接入或统一生产权限平台。

## Reliability

LLM Client 使用显式 timeout、retryable classification、有界次数、指数 backoff 和 jitter。Graph 保留 max_steps 预算与 Tool 游标。持久化确认丢失与已知执行失败分开处理；恢复读取新鲜事实，不将异常等同于数据库回滚。

## Safety

Tool metadata 来自可信注册层；只有明确 side_effect_free 才自动执行，其他调用 fail closed。Approval 是独立授权对象。暂停、拒绝与批准认领通过短事务和条件写入维持业务一致性。受保护执行复核审批与调用身份，不相信模型提供的安全声明。

## Durability

Task UUID 关联稳定 thread_id。checkpoint 只保存可序列化执行状态，fresh Runtime 可继续已有 thread。checkpoint-first pause 后原子写入 Approval 与 WAITING_APPROVAL Task；不同提交边界之间仍可能出现待核对窗口。

Ledger 保存独立执行 UUID、稳定 key 与 EXECUTING/SUCCEEDED/FAILED/UNKNOWN。成功记录可以重用，唯一约束和条件 claim 控制竞争。该机制不提供所有请求、所有 Tool 和外部系统的 universal exactly-once。

## Recovery

操作者经 API 调用 TaskRecoveryService，读取 Task、Approval、Checkpoint 和 Ledger，判断 no action、still in progress、orphan checkpoint、recovered 或 recovery required。stale 不是死亡证明；EXTERNAL_KEY/INHERENT 的恢复依赖真实能力与匹配上下文，NONE 的不确定结果不盲目重放。已完成 Graph 的结果可用于条件修复 Task，无需重新执行。

generation fencing 以预期状态和准确 updated_at 防止旧执行者覆盖新一代结果。恢复不是后台自动修复器，也没有 force replay、孤儿清理、补偿事务或通用 reconciliation。

## Observability

18 类 JSON 生命周期事件，使用 request/task/thread/approval/execution/ToolCall ID 关联；ContextVar 隔离请求，属性 allowlist 排除敏感正文和凭据。sink 故障不改变业务语义，但输出为 best-effort，可能丢失或增加延迟。它不是持久化审计、指标系统或分布式追踪后端。

## Testing

正式 Reviewer / CI 全量基线：**440 passed、0 failed、0 skipped、0 warnings**。覆盖 unit、integration、真实 PostgreSQL、checkpoint、并发、恢复、故障注入和 E2E。Focused 与 high-risk 是子集，不叠加计算。容器交付另验证空卷初始化、重启保留、API smoke、非 root/PID 1 和失败退出。

本轮仅包装文档，不重新运行全套测试。已有计数以 CURRENT_STATE 为来源；本轮文档、路径、Mermaid 与 Git 检查记录在 [TASK-034](../tasks/TASK-034.md)。TASK-034 Review 已确认 3/3 Mermaid diagrams、6/6 PowerShell blocks、23 local Markdown links 与 Compose configuration valid。

## Container

**Container Delivery = Qualified。** Python 3.11、UID 10001、PostgreSQL 17；Compose 等待 TCP health 后依次初始化业务 schema 与 framework schema，最后 exec Uvicorn。入口失败非零退出且不输出原始配置异常。backend health 是 HTTP liveness，开发凭据和 loopback 端口不是生产部署方案。

## CI

**CI Automation = Qualified；GitHub-hosted CI Run = PASS。** 当前状态快照已记录 hosted 验证通过。Workflow 对 main push/PR 运行依赖安装、pip check、Alembic、PostgresSaver、drift check、零 skip/warning 全量门禁和无缓存镜像构建；没有 registry push 或部署任务。本轮没有触发或独立重跑 hosted job，也未获得可引用的具体 run URL，因此不编造链接。

## Known Boundaries

Deployment Qualification 与 production-grade Provider Qualification 尚未完成。没有 worker/queue scheduler、后台恢复器、universal exactly-once、persistent audit log、distributed tracing backend、Prometheus/Grafana、multi-agent orchestration 或 MCP。Docker 镜像标签与现有未直接固定的传递依赖也不是字节级供应链锁定。

这些属于范围或未来验收，不自动归为 Technical Debt。既有维护项以 [TECH_DEBT](TECH_DEBT.md) 为准；旧 warning 记录不改变当前全量基线 0 warnings 的事实。

## Key Engineering Lessons

1. 编排状态、业务授权与外部副作用是三个不同问题，选用 workflow 框架后仍需明确各自事实来源。
2. timeout 或 commit 异常只说明确认路径失败，不一定说明操作未发生。
3. checkpoint 顺序、短事务、唯一约束与条件更新必须协同设计；单个“幂等”标签不足以承诺 exactly-once。
4. 可观测性要描述已确认事实，失败事件也不能泄露原始业务内容。
5. 单元测试之外需要真实数据库、并发竞争、故障注入和 fresh-process 证据；本地成功、hosted CI 与生产部署是不同验收。
6. 清晰文档应说明默认可演示能力、受控验证范围和未完成边界，避免用未测量的线上指标包装项目。

## Handoff

运行与演示从 README 开始；讲解材料见 [RESUME](RESUME.md) 和 [INTERVIEW_GUIDE](INTERVIEW_GUIDE.md)。Core runtime、reliability、Container Delivery、CI Automation、real Provider HTTP E2E validation 与 final packaging 已完成。Deployment Qualification 与 production-grade Provider Qualification 仍未完成，不构成 active task；最终状态以 CURRENT_STATE 与 AI_HANDOFF 为准。
