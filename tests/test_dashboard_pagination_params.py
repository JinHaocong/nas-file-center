from __future__ import annotations

from pathlib import Path


def test_dashboard_uses_explicit_page_and_page_size_params():
    dashboard_file = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "Dashboard" / "index.tsx"
    assert dashboard_file.exists()

    content = dashboard_file.read_text(encoding="utf-8")

    # Assert Dashboard passes (1, 5) instead of single argument (5)
    assert "scansApi.listScans(1, 5)" in content, "Dashboard must call scansApi.listScans(1, 5)"
    assert "tasksApi.listJobs(1, 5)" in content, "Dashboard must call tasksApi.listJobs(1, 5)"

    # Ensure incorrect listScans(5) or listJobs(5) is NOT present
    assert "scansApi.listScans(5)" not in content
    assert "tasksApi.listJobs(5)" not in content
