"""The formal gate must reject green pytest exits with skipped tests or warnings."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.qualified_tests import QualificationGate, main


@pytest.mark.parametrize("event", ["test_skip", "collection_skip", "warning"])
def test_gate_rejects_incomplete_or_warning_run(event):
    def run(args, plugins):
        gate = plugins[0]
        if event == "warning":
            gate.pytest_warning_recorded(None, None, None, None)
        elif event == "collection_skip":
            gate.pytest_collectreport(SimpleNamespace(skipped=True))
        else:
            gate.pytest_runtest_logreport(SimpleNamespace(skipped=True))
        return 0
    with patch("scripts.qualified_tests.pytest.main", side_effect=run):
        assert main() == 1


@pytest.mark.parametrize("result", [0, 1, 2, 5])
def test_gate_preserves_pytest_exit_status(result):
    with patch("scripts.qualified_tests.pytest.main", return_value=result):
        assert main() == result


def test_passed_reports_do_not_count_as_skips():
    gate = QualificationGate()
    gate.pytest_runtest_logreport(SimpleNamespace(skipped=False))
    gate.pytest_collectreport(SimpleNamespace(skipped=False))
    assert gate.skipped == gate.warnings == 0
