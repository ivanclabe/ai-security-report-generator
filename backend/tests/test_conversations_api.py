"""Fase 6: reopening a conversation (or reloading the page) must show the same
report download card it showed live -- CONVERSATIONAL_EXPERIENCE.md. Before
this fix, GET /api/conversations/{id} never attached report info to history.

Fase 8 adds the rename/pin/delete CRUD tests and a golden-path system test --
this backend had zero HTTP-level coverage before Fase 5 (ARCHITECTURE_ASSESSMENT.md),
and rename/pin/delete specifically were still untested at this layer."""
from tests.conftest import auth_headers, parse_sse_events


def test_conversation_without_a_report_has_no_report_card(api_client):
    headers = auth_headers(api_client)
    conv = api_client.post("/api/conversations", headers=headers, json={}).json()

    detail = api_client.get(f"/api/conversations/{conv['id']}", headers=headers).json()
    assert detail["report"] is None


def test_reopening_a_conversation_reconstructs_the_report_card(api_client):
    headers = auth_headers(api_client)

    generate_res = api_client.post(
        "/api/reports/generate",
        headers=headers,
        json={"company": "ACME Corp", "start_date": "2025-08-01", "end_date": "2025-08-31"},
    )
    result = parse_sse_events(generate_res.text)[-1]
    conversation_id = result["conversation_id"]
    live_report = result["report"]

    detail = api_client.get(f"/api/conversations/{conversation_id}", headers=headers).json()

    assert detail["report"] is not None
    assert detail["report"]["report_id"] == live_report["report_id"]
    assert detail["report"]["version"] == live_report["version"]
    assert detail["report"]["section_count"] == live_report["section_count"]
    assert detail["report"]["objective"] == live_report["objective"]


def test_rename_conversation(api_client):
    headers = auth_headers(api_client)
    conv = api_client.post("/api/conversations", headers=headers, json={}).json()

    res = api_client.patch(f"/api/conversations/{conv['id']}", headers=headers, json={"title": "Nuevo título"})
    assert res.status_code == 200
    assert res.json()["title"] == "Nuevo título"

    detail = api_client.get(f"/api/conversations/{conv['id']}", headers=headers).json()
    assert detail["title"] == "Nuevo título"


def test_rename_conversation_rejects_empty_title(api_client):
    headers = auth_headers(api_client)
    conv = api_client.post("/api/conversations", headers=headers, json={}).json()

    res = api_client.patch(f"/api/conversations/{conv['id']}", headers=headers, json={"title": "   "})
    assert res.status_code == 422


def test_pin_and_unpin_conversation(api_client):
    headers = auth_headers(api_client)
    conv = api_client.post("/api/conversations", headers=headers, json={}).json()
    assert conv["is_pinned"] is False

    res = api_client.patch(f"/api/conversations/{conv['id']}/pin", headers=headers, json={"is_pinned": True})
    assert res.status_code == 200
    assert res.json()["is_pinned"] is True

    res = api_client.patch(f"/api/conversations/{conv['id']}/pin", headers=headers, json={"is_pinned": False})
    assert res.json()["is_pinned"] is False


def test_pinned_conversations_are_listed_before_others(api_client):
    headers = auth_headers(api_client)
    older = api_client.post("/api/conversations", headers=headers, json={}).json()
    newer = api_client.post("/api/conversations", headers=headers, json={}).json()

    # Without pinning, most-recent-first -- "newer" should already lead.
    listing = api_client.get("/api/conversations", headers=headers).json()
    assert [c["id"] for c in listing] == [newer["id"], older["id"]]

    # Pinning the older one must bring it to the front despite being older.
    api_client.patch(f"/api/conversations/{older['id']}/pin", headers=headers, json={"is_pinned": True})
    listing = api_client.get("/api/conversations", headers=headers).json()
    assert listing[0]["id"] == older["id"]


def test_delete_conversation_removes_it_and_its_messages(api_client):
    headers = auth_headers(api_client)
    conv = api_client.post("/api/conversations", headers=headers, json={}).json()
    api_client.post(f"/api/conversations/{conv['id']}/messages", headers=headers, json={"content": "hola"})

    res = api_client.delete(f"/api/conversations/{conv['id']}", headers=headers)
    assert res.status_code == 204

    res = api_client.get(f"/api/conversations/{conv['id']}", headers=headers)
    assert res.status_code == 404


def test_rename_nonexistent_conversation_returns_404(api_client):
    headers = auth_headers(api_client)
    res = api_client.patch("/api/conversations/conv-no-existe", headers=headers, json={"title": "x"})
    assert res.status_code == 404


def test_delete_nonexistent_conversation_returns_404(api_client):
    headers = auth_headers(api_client)
    res = api_client.delete("/api/conversations/conv-no-existe", headers=headers)
    assert res.status_code == 404


def test_golden_path_generate_rename_pin_download_delete(api_client):
    """One coherent end-to-end scenario chaining the operations a real session
    would perform, through the real HTTP API, real docx generation, and a real
    file download -- the closest this suite comes to a browser E2E test
    without introducing new tooling (see QUALITY_OBSERVABILITY.md)."""
    headers = auth_headers(api_client)

    generate_res = api_client.post(
        "/api/reports/generate",
        headers=headers,
        json={"company": "ACME Corp", "start_date": "2025-08-01", "end_date": "2025-08-31"},
    )
    result = parse_sse_events(generate_res.text)[-1]
    assert result["status"] == "ready", result
    conversation_id = result["conversation_id"]
    report_id = result["report"]["report_id"]

    rename_res = api_client.patch(
        f"/api/conversations/{conversation_id}", headers=headers, json={"title": "Informe de prueba E2E"}
    )
    assert rename_res.json()["title"] == "Informe de prueba E2E"

    pin_res = api_client.patch(
        f"/api/conversations/{conversation_id}/pin", headers=headers, json={"is_pinned": True}
    )
    assert pin_res.json()["is_pinned"] is True

    listing = api_client.get("/api/conversations", headers=headers).json()
    assert listing[0]["id"] == conversation_id  # ordering itself covered by
    # test_pinned_conversations_are_listed_before_others; here just confirming it's present

    download = api_client.get(f"/api/reports/{report_id}/download", headers=headers)
    assert download.status_code == 200
    assert len(download.content) > 0

    delete_res = api_client.delete(f"/api/conversations/{conversation_id}", headers=headers)
    assert delete_res.status_code == 204
    assert api_client.get(f"/api/conversations/{conversation_id}", headers=headers).status_code == 404
