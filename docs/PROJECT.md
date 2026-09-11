# AgentFlow-AI

## Project Goal / 项目目标

AgentFlow-AI is an enterprise-oriented AI agent backend. It is designed to execute multi-step tasks through the following controlled loop:

`Task → Planning / Reasoning → Tool Calling → Tool Result → State Update → Next Decision → Final Result`

中文释义：

AgentFlow-AI 面向企业级后端场景，目标不是提供一个只能进行问答的普通聊天机器人，而是让 Agent 围绕一个明确任务持续执行。系统需要能够理解任务、进行推理或规划、调用工具、处理工具结果、更新状态、决定下一步，并在完成或失败时给出最终结果。

项目还承担一个长期目标：建立可复用的 AI-assisted software development workflow。项目状态、架构约束、任务定义和决策必须写入仓库，使不同的 Coding Agent 能够基于相同事实持续工作。

## Core Capabilities / 核心能力

The following capabilities describe the completed core project and explicitly retained future directions. Current qualification is maintained in `docs/CURRENT_STATE.md`.

以下能力覆盖已完成的核心项目与明确保留的未来方向；当前 qualification 以 `docs/CURRENT_STATE.md` 为准。

### Task Execution / 任务执行

Accept a task and manage its execution from start to completion or failure.

中文释义：系统需要围绕任务管理完整生命周期，而不是只返回一次模型调用结果。任务最终应能明确处于完成、失败或等待状态。

### LLM Tool Calling / LLM 工具调用

Allow the LLM to request a named tool with structured inputs when reasoning requires an external action or data source.

中文释义：模型负责提出工具调用意图，系统负责校验和执行。这样可以把“模型决策”和“程序实际执行”分开，避免把所有流程硬编码或无审计地交给模型。

### Real Provider Validation / 真实 Provider 验证

The OpenAI-compatible LLM path, real Tool Calling, Tool execution and LLM → Tool → LLM loop have been validated against DeepSeek in the development environment. The integration remains provider-neutral; DeepSeek is a validated Provider, not an architecture binding.

中文释义：当前已通过真实 DeepSeek 验证 LLM、Tool Calling、Tool 执行和最终回答闭环，但架构仍保持 OpenAI-compatible、provider-neutral。该验证不等于生产 Provider 或生产部署 qualification。

### Tool Registry and Dispatch / 工具注册与分发

Register available tools, resolve a tool by name, validate its input, and dispatch it to the correct implementation.

中文释义：工具注册表是 Agent 可用能力的明确目录；分发器把模型返回的工具名称映射到真实实现。权限、超时和副作用控制均以此为边界，当前已建立相应的可靠性与安全策略。

### Agent Execution Loop / Agent 执行循环

Coordinate the repeated `LLM → Tool → Result → LLM` interaction and stop when a final result or a failure condition is reached.

中文释义：Runtime 必须控制循环边界、停止条件和错误路径，不能允许模型在没有限制的情况下无限调用工具。

### Task State Management / 任务状态管理

Represent lifecycle states such as `pending`, `running`, `completed`, `failed`, and `waiting_for_approval`.

中文释义：状态让系统知道任务现在处于哪个阶段，也让 API、恢复机制和审计记录拥有共同依据。当前项目已实现 Task Domain、PostgreSQL 持久化、查询、审批暂停、继续执行与恢复边界。

### Execution History / 执行历史

Record meaningful execution events, including decisions, tool calls, tool results, errors, and transitions.

中文释义：执行历史用于调试、审计和复盘，回答“Agent 做了什么、为什么失败、调用了什么工具”等问题。

### Retry and Timeout Control / 重试与超时控制

Bound waiting and retry behavior for tools and external services.

中文释义：外部服务可能失败或变慢，因此重试必须有次数、条件和边界，超时必须能让任务进入可解释的失败路径，而不是无限等待。

### Workflow Orchestration / 工作流编排

Combine explicit workflow states and transitions with LLM decision making where appropriate.

中文释义：稳定的业务步骤不应全部依赖模型自由发挥。当前通过 LangGraph StateGraph、显式状态和条件转移约束流程，再让 LLM 处理适合推理的部分。

### Human-in-the-loop / 人在回路

Pause for human approval before dangerous, irreversible, or business-critical actions.

中文释义：涉及外部副作用或高风险决策时，系统需要允许人工确认、暂停和恢复，不能默认让 Agent 直接执行。

### Observability / 可观测性

Provide structured logs, traces, metrics, and audit information sufficient to explain runtime behavior.

中文释义：可观测性不是附加装饰，而是判断稳定性和定位故障的基础。当前已实现结构化生命周期事件、关联 ID 和敏感数据保护；metrics、distributed tracing backend 与 persistent audit 仍属未来方向。

### Multi-agent Collaboration / 多 Agent 协作

Potentially separate planner, executor, and reviewer responsibilities in a later phase.

中文释义：多 Agent 会增加通信、状态和错误处理复杂度，因此属于后期能力。项目必须先证明单 Agent Runtime 的边界和可靠性。

## V1 Scope / V1 范围

V1 focuses only on the minimum core runtime:

* FastAPI backend
* LLM integration
* tool calling
* tool registry
* agent runtime
* basic task state
* unit testing
* integration testing

中文释义：V1 的目的，是建立可运行、可测试、边界清晰的 Agent 后端闭环；当前核心项目已进一步完成持久化任务生命周期、HITL、恢复、交付 qualification 与最终文档打包。

## Non-Goals for V1 / V1 暂不实现

V1 explicitly does not include:

* frontend UI
* Kubernetes
* large-scale distributed execution
* vector database
* multi-agent orchestration
* MCP
* message queue
* automatic modification of external GitHub repositories

中文释义：这些方向并非永远不做，而是当前不具备足够需求或安全边界。提前加入会扩大依赖、部署和运行时复杂度，掩盖 Agent Runtime 本身的问题。尤其是外部 GitHub 自动修改、分布式执行和多 Agent，都需要先建立权限、隔离、审批、持久化和故障恢复机制。

## Engineering Principles / 工程原则

1. **Prefer explicit architecture over framework magic.**

   Keep important runtime behavior visible and understandable. 在理解核心执行过程之前，不用框架黑盒替代架构设计。

2. **Introduce dependencies only when they solve an existing problem.**

   Follow `Problem → Requirement → Technology`, not `Technology → Find a use case`。依赖必须解决已确认的问题。

3. **Every important behavior should be testable.**

   Tool lookup, loop bounds, failure handling, and state transitions should have executable tests。测试是项目的可执行记忆。

4. **Persistent state must have a clearly defined source of truth.**

   Durable task state and Execution Ledger use PostgreSQL as the business source of truth; Redis may serve cache, temporary state, or locks. Redis must not be the only source of truth for durable Agent tasks。

5. **Agent execution must have bounded loops and failure handling.**

   Every loop needs explicit limits, timeout behavior, retry policy, and terminal failure states。

6. **Architecture changes should be recorded.**

   Important changes belong in `docs/DECISIONS.md`, not only in a chat transcript。

7. **Code, tests, and project documentation should remain synchronized.**

   A completed change requires the implementation, relevant tests, and documented project state to agree。

## Source of Truth / 项目事实来源

The Git repository is the project source of truth. Chat history is not the project source of truth.

中文释义：需要长期保留的事实必须进入源代码、测试、项目文档、架构决策或 Git 历史。聊天记录只用于当前讨论和推理，不能替代仓库中的可审查记录。
