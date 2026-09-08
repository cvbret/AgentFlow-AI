# TASK-025 - Approval Decision to Task Lifecycle Integration

## Objective

Integrate human rejection into Task lifecycle without treating it as execution failure or implementing resume.

## Scope

Task REJECTED domain state, atomic Approval/Task rejection persistence, status filtering compatibility, and database regressions.

## Requirements

- Only WAITING_APPROVAL → REJECTED is legal; REJECTED is terminal with result=None and error=None.
- Approve keeps Task WAITING_APPROVAL. Reject produces REJECTED Approval and REJECTED Task in one short request-scoped transaction.
- ApprovalRejectionPersistence stages the PENDING-only Approval decision, then a WAITING-only Task rejection. Either zero-row conditional result rolls back and reports conflict. No unconditional Task overwrite.
- Standalone ApprovalRepository.save_decision_if_pending remains compatible; coordinated rejection uses stage_decision_if_pending and stage_rejected_if_waiting without intermediate commit.
- Rejection joins the short transaction opened by context reads; no LLM, Runtime, Tool or external wait occurs inside it.
- Statement/commit rejection rolls back both entities. Commit acknowledgement uncertainty propagates without fallback writes or reconciliation.
- Existing Approval endpoints and DTO remain. Task query/list accepts lowercase rejected. No migration is needed for VARCHAR status.

## Non-goals

No resume, checkpoint, approved execution, LLM continuation, idempotency framework, reconciliation, queue, worker, LangGraph or LangChain migration.

## Acceptance Criteria

Legal/illegal domain transitions; successful rejection atomicity; approve unchanged; single-winner approve/reject and same-decision concurrency; PostgreSQL statement and commit failure rollback; acknowledgement-loss preservation; REJECTED round-trip and filtering; no Tool/Runtime execution.

## Test Plan

Run focused Domain, Repository, decision/rejection, HITL and API suites against isolated PostgreSQL, then full pytest and git diff --check. Keep project completion state pending Independent Review.
