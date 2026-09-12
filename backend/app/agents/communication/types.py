"""Finite domain vocabulary, not routing instructions."""
from enum import StrEnum


class MessageType(StrEnum):
    REQUEST = "REQUEST"
    RESPONSE = "RESPONSE"
    RESULT = "RESULT"
    ERROR = "ERROR"
    HANDOFF = "HANDOFF"


class ArtifactType(StrEnum):
    PLAN = "PLAN"
    CODE_PATCH = "CODE_PATCH"
    TEST_REPORT = "TEST_REPORT"
