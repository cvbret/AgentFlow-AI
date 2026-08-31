# AgentFlow-AI

AgentFlow-AI is an enterprise-oriented AI agent backend for controlled multi-step task execution.

中文释义：项目目标是让 Agent 围绕任务进行推理、工具调用、状态更新和结果交付，而不是只提供普通聊天能力。

## Current Status / 当前状态

Phase 1 - Core Agent Runtime. The project is in active development.

当前正在建立项目基础和第一个可运行的 FastAPI backend。TASK-001 已定义，但尚未在本次文档任务中执行。

## Core Goal / 核心目标

Build a reliable, testable backend with an explicit execution flow:

`Task → Reasoning → Tool Calling → Tool Result → State Update → Final Result`

## Current Technology Stack / 当前技术栈

* Python
* FastAPI
* Uvicorn
* Pydantic
* pytest and HTTPX for testing

This list reflects the current repository baseline; future technologies require an explicit need and architectural decision.

## Project Documentation / 项目文档

* [`docs/PROJECT.md`](docs/PROJECT.md) — project goals, scope, principles, and source of truth
* [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — current logical architecture and dependency direction
* [`docs/ROADMAP.md`](docs/ROADMAP.md) — staged development roadmap
* [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md) — repository-confirmed current status
* [`docs/DECISIONS.md`](docs/DECISIONS.md) — architecture decision records
* [`docs/TECH_DEBT.md`](docs/TECH_DEBT.md) — intentionally accepted technical debt
* [`AGENTS.md`](AGENTS.md) — long-term AI Coding Agent rules
* [`tasks/TASK-001.md`](tasks/TASK-001.md) — first implementation task definition
