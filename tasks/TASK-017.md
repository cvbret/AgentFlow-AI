# TASK-017 - LLM Retry Timing Policy

## Objective

为 LLMClient 的 bounded retry 增加可配置、可测试的指数退避和最小 jitter，避免 retryable Provider failure 被立即连续请求。

## Scope

- 增加 `LLM_RETRY_BASE_DELAY_SECONDS` 配置，默认值为 `1.0`。
- retry delay 使用 `base_delay * 2^retry_index`，第一轮 retry 的 index 为 0。
- 增加有界 additive jitter，最终 delay 必须非负。
- LLMClient 支持注入 sleeper 和 jitter function；生产默认使用 `time.sleep` 和随机 jitter。
- 仅在存在下一次 attempt 时等待，Task 状态和 AgentRuntime 保持不变。

## Requirements

- 初始请求不得 sleep。
- `retryable=True` 且仍有 attempts 时，先 sleep 再 retry。
- non-retryable failure、`max_attempts=1` 和最终 failure 不得 sleep。
- 测试不得真实等待 backoff 时间。
- 不处理 Retry-After，不新增 retry framework。

## Non-goals

不实现 backoff strategy registry、circuit breaker、queue、worker、AgentRuntime retry、Tool retry、Task API 或新的外部框架。

## Acceptance Criteria

- 首次成功无等待。
- retryable failure 后的 delay 按指数增长并包含可控 jitter。
- `max_attempts=3` 最多 sleep 两次。
- non-retryable failure 不重复请求且不等待。
- 所有现有测试继续通过。

## Test Plan

- 使用 fake sleeper 验证 sleep 次数和 delay 序列。
- 注入确定性 jitter 验证 jitter 边界与非负 delay。
- 覆盖首次成功、retry 后成功、attempts exhausted、non-retryable 和 `max_attempts=1`。
- 执行 LLM focused tests 及 backend 全量 pytest。
