"""Contracts for the descriptive Agent layer; no database or provider needed."""

import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.agents import (
    Agent,
    AgentDefinitionError,
    AgentNotFoundError,
    AgentRegistry,
    AgentToolPermissionError,
    AgentToolPolicy,
    DuplicateAgentError,
)


def make_agent(**overrides) -> Agent:
    values = {
        "name": "planner",
        "role": "planning",
        "system_prompt": "Produce an implementation plan.",
    }
    values.update(overrides)
    return Agent(**values)


def test_agent_creation_and_json_round_trip():
    agent = make_agent(
        allowed_tools=["calculator", "repo_read"],
        metadata={"labels": ["demo"], "options": {"enabled": True, "limit": 2}},
    )
    assert agent.name == "planner"
    assert agent.role == "planning"
    assert agent.system_prompt == "Produce an implementation plan."
    assert agent.allowed_tools == frozenset({"calculator", "repo_read"})
    assert Agent.model_validate_json(agent.model_dump_json()) == agent


def test_defaults_are_empty_and_metadata_is_not_shared():
    first, second = make_agent(), make_agent(name="tester")
    assert first.allowed_tools == frozenset()
    assert first.metadata == {}
    first.metadata["note"] = "local"
    assert second.metadata == {}


@pytest.mark.parametrize("field", ["name", "role", "system_prompt"])
@pytest.mark.parametrize("value", ["", " \n\t", None, 123])
def test_required_strings_reject_invalid_values(field, value):
    with pytest.raises(ValidationError):
        make_agent(**{field: value})


@pytest.mark.parametrize("field", ["name", "role", "system_prompt"])
def test_required_strings_cannot_be_omitted(field):
    values = make_agent().model_dump()
    del values[field]
    with pytest.raises(ValidationError):
        Agent(**values)


@pytest.mark.parametrize("tools", [[""], ["  "], [12], [None], "calculator"])
def test_invalid_tool_grants_are_rejected(tools):
    with pytest.raises(ValidationError):
        make_agent(allowed_tools=tools)


def test_inputs_are_defensively_copied():
    tools = ["calculator"]
    metadata = {"nested": {"labels": ["original"]}}
    agent = make_agent(allowed_tools=tools, metadata=metadata)
    tools.append("shell")
    metadata["nested"]["labels"].append("changed")
    assert agent.allowed_tools == frozenset({"calculator"})
    assert agent.metadata == {"nested": {"labels": ["original"]}}


@pytest.mark.parametrize(
    "field,value",
    [("name", "other"), ("role", "other"), ("system_prompt", "other"),
     ("allowed_tools", frozenset({"shell"})), ("metadata", {})],
)
def test_fields_cannot_be_reassigned(field, value):
    with pytest.raises(ValidationError):
        setattr(make_agent(), field, value)


def test_tool_grants_cannot_be_mutated_in_place():
    agent = make_agent(allowed_tools=["calculator", "calculator"])
    assert len(agent.allowed_tools) == 1
    with pytest.raises(AttributeError):
        agent.allowed_tools.add("shell")


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        make_agent(runtime="not a model field")


@pytest.mark.parametrize("metadata", [{"object": object()}, {"value": float("inf")}])
def test_metadata_requires_json_values(metadata):
    with pytest.raises(ValidationError):
        make_agent(metadata=metadata)


def test_registry_register_get_and_ordered_list_copy():
    registry = AgentRegistry()
    assert registry.list() == []
    first, second = make_agent(), make_agent(name="tester")
    registry.register(first)
    registry.register(second)
    assert registry.get("planner") is first
    assert registry.list() == [first, second]
    registry.list().clear()
    assert registry.list() == [first, second]


def test_duplicate_registration_cannot_replace_original():
    registry = AgentRegistry()
    original = make_agent()
    registry.register(original)
    with pytest.raises(DuplicateAgentError):
        registry.register(make_agent(allowed_tools=["shell"]))
    assert registry.get("planner") is original
    assert not AgentToolPolicy().is_allowed(registry.get("planner"), "shell")


def test_registry_missing_name_is_explicit_and_case_sensitive():
    registry = AgentRegistry()
    registry.register(make_agent())
    for name in ("missing", "Planner"):
        with pytest.raises(AgentNotFoundError):
            registry.get(name)


@pytest.mark.parametrize("value", [None, {}, "planner"])
def test_registry_rejects_non_agents(value):
    registry = AgentRegistry()
    with pytest.raises(AgentDefinitionError):
        registry.register(value)
    assert registry.list() == []


@pytest.mark.parametrize(
    "tool_name,expected",
    [("calculator", True), ("shell", False), ("Calculator", False),
     ("calculator ", False), ("", False)],
)
def test_policy_exact_allow_deny(tool_name, expected):
    agent = make_agent(allowed_tools=["calculator"])
    policy = AgentToolPolicy()
    assert policy.is_allowed(agent, tool_name) is expected
    if expected:
        assert policy.ensure_allowed(agent, tool_name) is None
    else:
        with pytest.raises(AgentToolPermissionError):
            policy.ensure_allowed(agent, tool_name)


def test_default_deny_and_no_wildcard_expansion():
    policy = AgentToolPolicy()
    assert not policy.is_allowed(make_agent(), "calculator")
    assert not policy.is_allowed(make_agent(allowed_tools=["*"]), "shell")


def test_metadata_cannot_grant_permissions():
    agent = make_agent(metadata={"allowed_tools": ["shell"], "approved": True})
    assert not AgentToolPolicy().is_allowed(agent, "shell")


def test_role_grant_does_not_override_existing_tool_safety():
    from app.tools.exceptions import ToolExecutionError
    from app.tools.policy import ToolExecutionPolicy
    from app.tools.schemas import ToolMetadata

    agent = make_agent(allowed_tools=["write_file"])
    AgentToolPolicy().ensure_allowed(agent, "write_file")
    metadata = ToolMetadata(
        name="write_file", description="Protected", input_schema={"type": "object"}
    )
    with pytest.raises(ToolExecutionError):
        ToolExecutionPolicy().ensure_automatic_execution_allowed(metadata)


def test_abstraction_import_does_not_load_execution_dependencies():
    # A fresh interpreter is essential: other tests import the legacy Runtime.
    script = (
        "import sys; from app.agents import Agent, AgentRegistry, AgentToolPolicy; "
        "assert not any(k.startswith(('app.agents.runtime', 'app.workflows', "
        "'app.tools', 'app.db', 'langgraph', 'sqlalchemy')) for k in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        capture_output=True, text=True, check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr


def test_legacy_package_exports_keep_identity():
    import app.agents as package
    from app.agents.runtime import (
        AgentError, AgentMaxStepsExceededError, AgentResult, AgentRuntime,
    )

    assert package.AgentError is AgentError
    assert package.AgentMaxStepsExceededError is AgentMaxStepsExceededError
    assert package.AgentResult is AgentResult
    assert package.AgentRuntime is AgentRuntime
    with pytest.raises(AttributeError):
        getattr(package, "missing_export")
