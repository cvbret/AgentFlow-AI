# AI Coding Agent Project Rules

This file defines the long-term operating rules for AI Coding Agents working in AgentFlow-AI. The repository is the source of truth; do not infer project state from chat history when the repository can be inspected.

本文是 AI Coding Agent 的长期项目规范。Agent 应以仓库中的代码、测试和文档为依据，不依赖聊天记录猜测项目状态。

## Before Making Changes / 修改前

Before starting work, read:

1. `docs/PROJECT.md`
2. `docs/ARCHITECTURE.md`
3. `docs/CURRENT_STATE.md`
4. `docs/AI_HANDOFF.md` when applicable
5. the active `tasks/TASK-XXX.md`
6. relevant source files
7. relevant tests

中文释义：先理解项目目标、当前架构、真实状态、当前任务和受影响代码，再修改。若任务与文档冲突，应先识别冲突，不要默默扩大范围。

## AI Context and Handoff Rules / AI 上下文与交接规则

`docs/AI_HANDOFF.md` 用于帮助新的 AI assistant 或 Coding Agent 快速恢复项目快照。适用时应阅读，但它不是代码 Requirement 的替代品。

项目上下文由以下部分组成：

```text
Stable Context
  + Current State
  + Current Task
  + Relevant Code
```

如果 `AI_HANDOFF.md` 与其他事实冲突，优先级为：

1. actual code / tests
2. active task
3. `docs/CURRENT_STATE.md`
4. architecture / decisions
5. `docs/AI_HANDOFF.md`

发现冲突时必须在任务报告中明确说明，不得静默选择一个版本继续执行。

## Scope Rules / 范围规则

* Modify only files required by the active task.
* Do not perform unrelated refactoring.
* Do not add unnecessary dependencies.
* Do not make silent architecture changes.
* Do not introduce LangChain, LangGraph, MCP, Multi-Agent, Kubernetes, message queues, or vector databases before an explicit requirement and decision.

中文释义：每次任务都应有清晰边界。技术方案不能因为“以后可能有用”就提前加入；重大架构变化必须记录到 `docs/DECISIONS.md`。

## Testing Rules / 测试规则

* Do not delete tests just to make CI pass.
* Do not weaken assertions just to make tests pass.
* Do not hide failures.
* Add tests for important new behavior whenever practical.

测试失败应被解释和修复，而不是通过删除测试、降低断言或隐藏错误来制造绿色结果。

## Architecture Rules / 架构规则

Follow `docs/ARCHITECTURE.md`.

* Architecture decisions belong in `docs/DECISIONS.md`.
* Known and intentionally accepted compromises belong in `docs/TECH_DEBT.md`.
* Keep API, application, runtime, tool, and infrastructure responsibilities separated.

## Completion Report / 完成报告

At the end of a task, report:

1. files changed
2. what was implemented
3. tests executed
4. test results
5. architecture impact
6. remaining risks
7. technical debt introduced

## Important State Rule / 重要状态规则

An agent must not mark a task as Completed in `docs/CURRENT_STATE.md` merely because it wrote the code.

Required flow:

```text
Implementation
  ↓
Tests
  ↓
Independent Review
  ↓
Fix if needed
  ↓
Validation
  ↓
Project State Synchronization
```

中文释义：只有实现、测试、独立检查和最终验证都完成后，才能同步项目状态。开发者“写完了”不等于任务已经被项目确认完成。
