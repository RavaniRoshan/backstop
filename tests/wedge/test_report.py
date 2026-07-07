import pytest
from wedge.report import generate_report

def test_generate_report():
    diff_results = {
        "main.py": {
            "status": "converged",
            "average_similarity": 1.0,
            "patches": ["patch A", "patch A"]
        }
    }
    runners = [
        {"runner_id": "R0", "test_passed": True, "budget_remaining": 15000},
        {"runner_id": "R1", "test_passed": False, "budget_remaining": 10000},
    ]
    
    report = generate_report("Test Task", diff_results, runners)
    
    assert "Wedge Run Report: Test Task" in report
    assert "Runner R0" in report
    assert "Budget remaining: 15000" in report
    assert "Runner R1" in report
    assert "Tests passed: False" in report
    assert "File: `main.py`" in report
    assert "CONVERGED" in report
    assert "patch A" in report
