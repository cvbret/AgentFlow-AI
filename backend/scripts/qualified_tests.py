"""Run from backend: python -m scripts.qualified_tests [pytest arguments]."""
import sys
import pytest


class QualificationGate:
    def __init__(self):
        self.skipped = 0
        self.warnings = 0

    def pytest_runtest_logreport(self, report):
        if report.skipped:
            self.skipped += 1

    def pytest_collectreport(self, report):
        if report.skipped:
            self.skipped += 1

    def pytest_warning_recorded(self, warning_message, when, nodeid, location):
        self.warnings += 1


def main():
    gate = QualificationGate()
    result = pytest.main(sys.argv[1:] or ["-q"], plugins=[gate])
    print(f"Qualification gate: {gate.skipped} skipped, {gate.warnings} warnings")
    return int(result) if result else int(bool(gate.skipped or gate.warnings))


if __name__ == "__main__":
    raise SystemExit(main())
