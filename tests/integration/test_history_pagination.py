"""History browsing can span more than the first 20 runs without losing comparisons."""

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from runtime.state import RunStore


def test_history_api_pages_cover_all_runs(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    for i in range(27):
        store.create(f"{i:032x}", "deseq2-basic")
    with patch("app.main.store", store):
        client = TestClient(app)
        first = client.get("/api/v1/runs", params={"limit": 20, "offset": 0})
        second = client.get("/api/v1/runs", params={"limit": 20, "offset": 20})
    assert first.status_code == second.status_code == 200
    first_data, second_data = first.json(), second.json()
    assert first_data["total"] == second_data["total"] == 27
    assert len(first_data["runs"]) == 20
    assert len(second_data["runs"]) == 7
    assert not ({r["run_id"] for r in first_data["runs"]}
                & {r["run_id"] for r in second_data["runs"]})


def test_history_ui_exposes_navigation_and_persistent_comparison_controls() -> None:
    response = TestClient(app).get("/")
    assert response.status_code == 200
    page = response.text
    for control in (
        'id="history-previous"',
        'id="history-next"',
        'id="history-clear-selection"',
        'id="history-selection-summary"',
    ):
        assert control in page
    assert 'offset: String(historyOffset)' in page
    assert 'historyOffset += historyPageSize' in page
    assert 'historyOffset = Math.max(0, historyOffset - historyPageSize)' in page
    assert 'compareSelection.clear()' in page
    assert 'compareSelection.delete(selected)' not in page
    assert 'historyStatus.addEventListener("change", function () {' in page
