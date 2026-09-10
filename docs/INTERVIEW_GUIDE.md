# AgentFlow-AI 面试讲解指南

## 项目 1 分钟介绍

AgentFlow-AI 是一个执行型 Agent 后端。它把一次模型请求组织为有持久化状态的 Task，支持 Tool 调用、人工审批、进程重启后继续执行和故障恢复。FastAPI 提供接口，PostgreSQL 保存业务事实，LangGraph 负责 workflow 编排和 checkpoint。项目自己的代码负责审批、安全、LLM 重试、Execution Ledger 和恢复判断。重点是副作用发生后结果不确定时，不能直接重试：先核对持久化证据，能够安全继续才继续，否则进入 RECOVERY_REQUIRED。正式基线为 440 项测试全部通过，Docker 和 hosted CI 已验收；生产部署与真实 provider 生产验证还没有完成。

## 项目 3 分钟介绍

可以按“问题—执行—异常—证据”来讲。

**问题：** 模型提出调用外部 Tool 的意图后，系统还需要判断是否安全、是否获得授权、结果是否真正保存。人类审批可能晚于原始请求，执行进程也可能中断，因此不能只把状态保存在内存。

**执行：** 请求经 FastAPI 进入 Task/Application Services，创建并推进持久化 Task。AgentRuntime 对接 LangGraph，运行有 max_steps 上限的 LLM/Tool 循环。明确无副作用的 Tool 可以自动执行；其他 Tool 被默认拦截。需要审批时先保存 checkpoint，再原子写入 PENDING Approval 与 WAITING_APPROVAL Task。approve 竞争一次 continuation claim，之后即使重建 Runtime/Saver，也可以从原 thread 和游标继续。

**异常：** 执行完成和结果写入不是同一件事。Execution Ledger 保存稳定执行身份，SUCCEEDED 可直接复用结果；UNKNOWN 不能盲目重试。恢复入口会检查 Task、Approval、Checkpoint 和 Ledger，结合新鲜度、身份与 Tool 的幂等能力决定继续、缓存复用、无动作或 RECOVERY_REQUIRED。generation fencing 防止旧执行者覆盖新一代结果，但不能取消已经发生的外部副作用。

**证据与边界：** 已有 440 项全量测试，涵盖数据库、并发、checkpoint、恢复和 E2E。Docker 明确双 schema 初始化，CI 将 skip/warning 视为不合格，hosted run 已 PASS。这里的成功来自受控 provider/Tool 和实际数据库验证，没有证明生产部署、真实服务的幂等契约或通用 exactly-once。

## 核心架构解释

API 管 HTTP 协议；Application Services 管 Task/Approval 生命周期与事务协调；AgentRuntime 是应用调用 façade；LangGraph 管图状态、checkpoint 和 interrupt/resume；LLM Client 与 Tool subsystem 管各自协议和执行边界。Repository 将 Domain 映射为数据库 Record，业务表与 checkpoint 表有不同 owner。三张概览图见 [README](../README.md)。

## 为什么自研 Runtime？

“自研”是把本项目需要负责的契约写清楚，不是重新实现所有框架能力。模型通信、审批授权、Tool safety、执行身份、恢复分类和 API 语义需要匹配业务。当前 AgentRuntime 作为 façade 使用 LangGraph 编排，避免同时维护两套 Agent 主循环。

## LangGraph 做了什么？

它提供 StateGraph orchestration、状态推进、checkpoint 和 interrupt/resume。PostgresSaver 提供 PostgreSQL 持久化。它没有替项目决定谁能审批、UNKNOWN 能否重试或哪些事件可以记录。把框架的编排能力与应用策略分离，才能分别验证和演进。

## 为什么需要 Approval？

Task 表示任务生命周期，Approval 表示某个具体 ToolCall 的授权决定。把二者分开才能校验 task_id、ToolCall、参数和决策是否对应，并通过事务与条件更新处理重复或竞争审批。模型说“这个操作安全”不能替代可信 policy 与持久化的人类授权。

## 为什么需要 durable checkpoint？

进程内存会在重启后消失。checkpoint 保存当前 workflow 状态与位置，稳定 thread_id 让新 Runtime 找回同一条执行链。但 checkpoint 只说明执行状态，不能替代 Approval 的授权真相，也不保证业务表与外部系统同时提交。

## 为什么要 Execution Ledger？

checkpoint 保存“图走到哪里”，Ledger 保存“这个受保护操作执行到什么结果”。例如 Tool 已成功而图尚未写入下一 checkpoint，恢复时仅看图可能再次调用 Tool。Ledger 的 SUCCEEDED 结果可以被复用，数据库唯一约束与 claim 也可阻止普通并发重复执行。它的范围是受保护执行，不是整个 HTTP 请求的全局去重。

## 为什么 UNKNOWN 不能自动 retry？

UNKNOWN 表示外部效果不确定，而不是已确认没有发生。例如对方已经处理请求，但网络在返回结果前断开。再次调用可能重复产生副作用，因此普通路径停止；只有恢复服务确认授权、执行身份、新鲜度与幂等能力都符合条件，才可能继续。NONE 类型不确定操作不能靠 retry 猜答案。

## 为什么 EXTERNAL_KEY 可以安全恢复？

前提是 Tool 真的把同一个稳定 key 交给支持幂等处理的外部系统，而且外部系统的有效期、作用域和参数一致性契约成立。项目恢复保留 execution UUID/key、复核 Approval 与上下文，并条件认领一次恢复尝试。仅声明 EXTERNAL_KEY 不会让任意外部接口自动幂等；再次结果不明仍会保持保守状态。真实 provider 的该契约需要单独验证。

## INHERENT 与 EXTERNAL_KEY 有何不同？

INHERENT 表示操作本身重复执行不会增加额外效果；EXTERNAL_KEY 依赖外部系统按 key 去重。两者都必须由可信 Tool 实现承担契约，不能由模型动态声明。恢复仍会校验同一调用身份和授权，不因存在能力标记就跳过所有检查。

## RECOVERY_REQUIRED 是什么？

它表示活动任务当前无法安全自动继续，需要进一步核对证据。它不同于已知失败 FAILED，也不同于人工拒绝 REJECTED。它不是“强制重试”按钮：再次调用恢复仍须通过相同安全判断，没有补齐证据就不能宣称恢复成功。

## stale RUNNING / EXECUTING 是否说明旧进程已死？

不说明。updated_at 超过阈值只允许评估恢复，慢执行者仍可能存活。最近有活动的任务/记录会返回 STILL_IN_PROGRESS。当前没有 worker lease、heartbeat 或后台扫描器；不能把时间阈值当成进程死亡证明。

## generation fencing 是什么？

可把它理解为“只允许持有当前代际的人落笔”。服务记录预期 RUNNING 状态和准确 updated_at，完成、失败或暂停时使用条件 UPDATE。若另一恢复者已经认领并推进时间戳，旧执行者的更新影响零行，不能无条件覆盖新结果。Ledger 结果也有对应执行代际保护。它保护数据库状态写入，不是跨系统分布式锁。

## commit acknowledgement uncertainty 是什么？

数据库可能已经 commit，但返回确认时连接断开。调用方看到异常，并不能证明回滚。如果此时把成功操作改写成失败或重新执行，就可能制造错误。当前实现区分本地持久化确认不确定与已知执行失败，保留必要状态，恢复时通过新 Session/Runtime 重新读取 durable truth；如果 SUCCEEDED 已持久化，就复用结果。

## recovery 与 reconciliation 有什么关系？

recovery 是恢复入口和安全继续过程；reconciliation 是核对并调整不一致的持久化事实。例如 Graph 已经 END 且保存了最终回答，但 Task 仍为 stale RUNNING，可以条件补齐 Task 结果而不调用 LLM/Tool。缺失或不匹配证据不能凭空补造；孤儿 checkpoint 只报告，不自动清理。

## observability 如何保证不影响业务？

事件和 sink 采用 best-effort 边界，构造、序列化或输出异常不会改变业务结果。属性 allowlist 排除敏感正文，ContextVar 在结束时复位，事件遵循确认提交和代际事实。这里的“不影响”是失败隔离的业务语义，不是零延迟：同步 sink 仍可能增加耗时，日志也可能丢失，因此不是 durable audit。

## Docker / CI 如何提高可重复交付？

Docker 固定 Python 主版本、工作目录、依赖安装和非 root 运行方式；Compose 等待 PostgreSQL TCP healthy，再执行 Alembic 与 PostgresSaver setup，最后 exec Uvicorn。CI 在 PostgreSQL 服务上跑同样的初始化、全量测试和镜像构建。它约束开发环境差异，但浮动镜像标签及既有传递依赖意味着不是字节级锁定供应链，更不能代替生产部署验收。

## 为什么不继续做 worker / queue / Kubernetes？

当前目标是证明单 Agent 执行与恢复边界。加入异步 worker 后还要定义租约、liveness、取消、权限、迁移并发和运维责任。没有相应需求与验收标准时，先把当前能力和限制交付清楚，比用基础设施数量衡量项目成熟度更有意义。

## 如何回答“项目有多成熟”？

准确说：核心、工程可重复性、Docker 和 CI 已验证，正式全量 440 passed、0 failed/skipped/warnings，GitHub-hosted CI Run PASS。受控测试覆盖的结论不能推广为真实业务 SLA；生产部署、真实 provider 生产验证、通用 exactly-once、persistent audit、tracing backend、multi-agent 和 MCP 均不在当前完成范围。

## 建议演示顺序

先用 Docker 展示 health、Task 列表和 `/docs`；再从 README 的三张图讲解审批与恢复；最后运行 `tests/test_release_e2e.py` 展示受控 provider 的关键链路。默认 Calculator 不会自动触发受保护审批，不要在演示中暗示项目已连接真实外部副作用服务。所有测试使用独立可丢弃数据库。
