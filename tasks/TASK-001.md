# TASK-001 - Minimal FastAPI Application

## Goal / 目标

Create the minimal runnable FastAPI backend for AgentFlow-AI.

中文释义：先提供一个可启动、可探活的最小后端，为后续 LLM 和 Agent Runtime 开发建立稳定入口。

## Scope / 范围

* `backend/app/`
* `backend/tests/` only as required to test this task

## Requirements / 要求

1. Create a FastAPI application.
2. Set the application title to `AgentFlow AI`.
3. Set the application version to `0.1.0`.
4. Add `GET /api/health`.
5. Return this JSON response:

   ```json
   {
     "status": "ok"
   }
   ```

6. The application must be runnable using Uvicorn.

中文释义：本任务只验证服务骨架、应用元信息和健康检查接口。健康检查应返回稳定的 HTTP 200 和固定 JSON，便于后续本地运行与自动化验证。

## Architecture Constraints / 架构约束

Do not:

* add Agent Runtime
* add a database
* add LangChain
* add LangGraph
* add a Tool Registry
* perform unrelated refactoring
* introduce unnecessary dependencies

这些内容属于后续阶段；本任务不应借机扩大架构。

## Tests / 测试

Add an automated test for `GET /api/health`.

Expected result:

* HTTP 200
* JSON body:

  ```json
  {
    "status": "ok"
  }
  ```

## Acceptance Criteria / 验收标准

* Relevant tests pass.
* The health API behaves according to the requirements.
* The FastAPI application can be started with Uvicorn.

## Completion Report / 完成报告

After implementation, report:

* changed files
* implementation
* tests
* test results
* architecture impact
* remaining risks

## Current Task Status / 当前任务状态

This file is a task definition only. TASK-001 has not been implemented by the documentation foundation task and must not be marked Completed in `docs/CURRENT_STATE.md`.

中文释义：本次文档基础设施任务只创建正式任务定义，不执行其中的业务代码开发。
