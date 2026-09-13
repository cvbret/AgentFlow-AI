"""Deterministic LLM fixture and bounded, memory-only protected Tool."""
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.agents.communication import AgentMessage, ArtifactType
from app.llm.schemas import LLMResponse, ToolCall
from app.tools.base import Tool
from app.tools.schemas import ToolResult
from app.tools.permission import current_tool_agent

USER_REQUEST = "Add non-blank name validation to the sample Python greeting service."
BEFORE = 'def greet(name):\n    return f"Hello, {name}!"\n'
AFTER = ('def greet(name):\n'
         '    if not isinstance(name, str) or not name.strip():\n'
         '        raise ValueError("name must be a non-blank string")\n'
         '    return f"Hello, {name.strip()}!"\n')
PATCH = {"sample": "greeting.py (synthetic, never written)", "before": BEFORE, "after": AFTER}


class StageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change: Literal["input_validation"]


class StageSamplePatch(Tool):
    name = "stage_sample_patch"
    description = "Stage the fixed greeting validation patch in volatile demo memory; requires human approval."
    input_schema = StageInput
    side_effect_free = False  # Appends to the caller-owned volatile staging list.
    # Inherited NONE: no claim of recovering a lost volatile workspace or uncertain effect.

    def __init__(self, effects: list[dict]):
        self.effects = effects
        super().__init__()

    def _execute(self, input_data: StageInput) -> ToolResult:
        self.effects.append({"owner_agent_id": current_tool_agent().name, "content": dict(PATCH)})
        return ToolResult(content=json.dumps(PATCH))


class ScriptedDemoLLM:
    """Offline fixture, not a real model or a general code generator/test runner."""

    def __init__(self, role: Literal["developer", "tester"]):
        self.role = role

    def chat(self, *, messages, tools):
        if self.role == "developer":
            outputs = [m for m in messages if m.role == "tool"]
            if outputs:
                return LLMResponse(content=outputs[-1].content)
            return LLMResponse(tool_calls=[ToolCall(id="stage_validation_patch",
                name="stage_sample_patch", arguments={"change": "input_validation"})])
        request = AgentMessage.model_validate_json(messages[-1].content)
        patch = request.artifacts[0]
        checks = {
            "code_patch_type": patch.artifact_type is ArtifactType.CODE_PATCH,
            "developer_owner": patch.metadata.get("owner_agent_id") == "developer",
            "expected_before": isinstance(patch.content, dict) and patch.content.get("before") == BEFORE,
            "expected_validation_patch": isinstance(patch.content, dict) and patch.content.get("after") == AFTER,
        }
        return LLMResponse(content=json.dumps({"status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks, "artifact_id": str(patch.artifact_id),
            "method": "Scripted fixture structure/content comparison; no generated code execution"}))

    def close(self):
        pass
