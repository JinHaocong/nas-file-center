from __future__ import annotations

from pathlib import Path


def test_dashboard_uses_explicit_page_and_page_size_params():
    dashboard_file = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "Dashboard" / "index.tsx"
    assert dashboard_file.exists()

    content = dashboard_file.read_text(encoding="utf-8")

    # Both lists must request page 1 with size 5, using the Task Center's
    # visibility-aware endpoint for recent jobs.
    assert "scansApi.listScans(1, 5)" in content
    assert "tasksApi.listTasks({ page: 1, pageSize: 5 })" in content

    # Old work-jobs bypasses dismissed failed-job visibility in earlier releases.
    assert "scansApi.listScans(5)" not in content
    assert "tasksApi.listJobs(" not in content
