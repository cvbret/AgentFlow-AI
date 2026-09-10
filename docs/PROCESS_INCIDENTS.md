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

## PI-002 - Workspace Boundary Incident during TASK-032 bootstrap

**Status:** `Mitigated`

**Severity:** `NOTE`

### Incident

首次 TASK-032 clean-environment virtual-environment bootstrap 时，TEMP/TMP
尚未重定向。`ensurepip` / `tempfile` 使用了继承的系统临时目录：

`C:\WINDOWS\TEMP`

### Classification

该事件属于 Workspace Boundary process incident，不是 product implementation defect。

### Actual Impact

已知涉及：

* temporary wheel/bootstrap files
* tempfile probe files

未观察到以下 repository 外写入：

* project source
* project configuration
* secrets
* test artifacts

### Evidence Limitation

未进行逐文件 OS-level forensic audit，因此不能绝对证明不存在任何残留文件。
当前结论基于执行过程、继承的临时目录和标准库行为检查；未发现可归属于此次事件的项目 artifact。

### Mitigation

后续 bootstrap、installation 和 temporary test setup 已在操作前将 TEMP/TMP
设置为 repository-owned temp directory。Reviewer 按修正流程独立执行，未观察到重复违规。

### Prevention

workspace safety-sensitive workflow 中，所有 venv bootstrap、pip installation
和 temporary test setup 必须先设置 repo-local TEMP/TMP，再执行相关操作。
