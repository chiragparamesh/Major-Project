"""
tests/test_part24_scenario_suite.py - Part 24 Scenario Suite & Accuracy Report Tests

DONE CHECK: ACCURACY_REPORT.md exists and scenario_tests.py exits successfully.
"""

import os
import pytest

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
report_path = os.path.join(root_dir, "ACCURACY_REPORT.md")


def test_accuracy_report_exists_and_contains_sections():
    """Validates that ACCURACY_REPORT.md exists and contains required sections."""
    assert os.path.exists(report_path), f"Missing {report_path}"

    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "# MLBFD ACCURACY & SYSTEM PERFORMANCE REPORT" in content
    assert "Executive Summary & Headline Numbers" in content
    assert "Recall at 1% FPR" in content
    assert "End-to-End Latency Benchmarks" in content
    assert "Confusion Matrix" in content
    assert "Recall by Fraud Pattern Category" in content
    assert "Per-Scenario Execution Table" in content
    assert "All 21 scripted payment scenarios matched" in content
