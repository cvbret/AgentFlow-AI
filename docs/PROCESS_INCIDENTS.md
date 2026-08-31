# AI-assisted Development Process Incidents

本文记录 AI-assisted development workflow 中已经确认的 process incident。

## PI-001 - Repository external write during TASK-004

**Status:** `Mitigated`

**Severity:** `Major Process Violation`

### Incident

TASK-004 Developer 因错误路径在 repository root 外创建文件：

`E:\AIProjects\晟\Documents\ChatGPT\AI_agent项目\backend\app\tools\registry.py`

该文件随后被删除。

### Impact

当前未发现其他项目代码被修改。错误文件已经删除，当前未发现代码文件残留。

### Root Cause

现有 Workspace Boundary 主要依赖文本规则和 Agent 自律，没有 filesystem sandbox enforcement。

### Mitigation

增加：

* repository root verification
* Planned Write Set
* repository-relative writes
* path containment check
* no-silent-cleanup reporting
* Reviewer boundary verification

### Remaining Risk

上述措施仍然属于 process-level guard，不能提供操作系统级 filesystem isolation。

真正的 Hard Boundary 未来需要 sandbox、container 或其他环境级隔离。
