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
