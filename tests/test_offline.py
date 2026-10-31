import json

from app.core import Store, grader, parse_analysis, run_analysis, stage_order


def test_default_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRIPTED_MODEL", "1")
    monkeypatch.setenv("APP_DATA", str(tmp_path))
    from app.core import baseline_instructions, instructions_path
    instructions_path().write_text(baseline_instructions())
    store = Store(tmp_path)
    record = run_analysis(store, "REV-100", ticket=store.ticket("REV-100"))
    assert record["status"] == "satisfied"
    assert record["turns"] == 9
    assert record["counts"] == {"Confirmed Facts": 3, "Ambiguities": 2, "Clarification Questions": 2, "Assumptions": 2}
    assert len(record["grading"]) == 2


def test_tools_and_parser(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRIPTED_MODEL", "1")
    monkeypatch.setenv("APP_DATA", str(tmp_path))
    store = Store(tmp_path)
    record = run_analysis(store, "REV-100", ticket=store.ticket("REV-100"), failures=2)
    assert record["trace"][1]["detail"].startswith("Error: 503")
    assert record["trace"][3]["detail"].startswith("Error: request timed")
    assert stage_order(record["analysis_markdown"])["complete"]
    parsed = parse_analysis(record["analysis_markdown"])
    assert "Summary" not in parsed["counts"]


def test_http_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA", str(tmp_path))
    monkeypatch.setenv("SCRIPTED_MODEL", "1")
    from app.core import create_app
    client = create_app().test_client()
    assert client.get("/").status_code == 200
    page = client.get("/api/pages").get_json()[0]["id"]
    response = client.post("/api/tickets", json={"title": "Review", "linked_page_id": page, "assignee": "Casey (QA Lead)"})
    assert response.status_code == 201
    ticket = response.get_json()
    assert ticket["status"] == "Analysis Ready"
    assert client.post(f"/api/tickets/{ticket['key']}/close").status_code == 200
    assert client.post(f"/api/tickets/{ticket['key']}/rerun").status_code == 409
