from app.models.employee import Employee
from tests.helpers import auth_headers, create_company, create_user, login


def _create_employee(db_session, company, user, employee_code) -> Employee:
    employee = Employee(
        user_id=user.id,
        company_id=company.id,
        employee_code=employee_code,
        joining_date="2026-01-01",
    )
    db_session.add(employee)
    db_session.commit()
    db_session.refresh(employee)
    return employee


def _setup_user_and_employee(client, db_session, company, email, employee_code):
    user = create_user(db_session, company, email, "Password123!", full_name=email.split("@")[0])
    employee = _create_employee(db_session, company, user, employee_code)
    token = login(client, email, "Password123!")
    return user, employee, token


def _create_project(client, token, key="DEV"):
    resp = client.post("/api/v1/projects", json={"key": key, "name": "Development"}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_ticket(client, token, project_id, summary="A task", **extra):
    issue_types = client.get("/api/v1/issue-types", headers=auth_headers(token)).json()
    resp = client.post(
        "/api/v1/tickets",
        json={"project_id": project_id, "summary": summary, "issue_type_id": issue_types[0]["id"], **extra},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_sprint_lifecycle_start_complete_moves_incomplete_to_backlog(client, db_session):
    company = create_company(db_session)
    _, _, token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    project = _create_project(client, token)

    sprint_resp = client.post(
        f"/api/v1/projects/{project['id']}/sprints", json={"name": "Sprint 1", "goal": "Ship it"}, headers=auth_headers(token)
    )
    assert sprint_resp.status_code == 201, sprint_resp.text
    sprint = sprint_resp.json()
    assert sprint["status"] == "future"

    ticket = _create_ticket(client, token, project["id"], sprint_id=sprint["id"])
    assert ticket["sprint_id"] == sprint["id"]

    start_resp = client.post(f"/api/v1/sprints/{sprint['id']}/start", headers=auth_headers(token))
    assert start_resp.status_code == 200
    assert start_resp.json()["status"] == "active"

    # A second sprint cannot be started while one is already active
    sprint2 = client.post(
        f"/api/v1/projects/{project['id']}/sprints", json={"name": "Sprint 2"}, headers=auth_headers(token)
    ).json()
    second_start = client.post(f"/api/v1/sprints/{sprint2['id']}/start", headers=auth_headers(token))
    assert second_start.status_code == 400

    # Completing the sprint with an unfinished ticket moves it to the backlog by default
    complete_resp = client.post(
        f"/api/v1/sprints/{sprint['id']}/complete", json={"incomplete_action": "backlog"}, headers=auth_headers(token)
    )
    assert complete_resp.status_code == 200
    assert complete_resp.json()["status"] == "completed"

    ticket_after = client.get(f"/api/v1/tickets/{ticket['id']}", headers=auth_headers(token)).json()
    assert ticket_after["sprint_id"] is None

    # A future sprint can now be started
    third_start = client.post(f"/api/v1/sprints/{sprint2['id']}/start", headers=auth_headers(token))
    assert third_start.status_code == 200


def test_board_shows_active_sprint_tickets_grouped_by_status(client, db_session):
    company = create_company(db_session)
    _, _, token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    project = _create_project(client, token)
    statuses = client.get(f"/api/v1/projects/{project['id']}/statuses", headers=auth_headers(token)).json()

    backlog_ticket = _create_ticket(client, token, project["id"], summary="No sprint")

    sprint = client.post(
        f"/api/v1/projects/{project['id']}/sprints", json={"name": "Sprint 1"}, headers=auth_headers(token)
    ).json()
    client.post(f"/api/v1/sprints/{sprint['id']}/start", headers=auth_headers(token))
    sprint_ticket = _create_ticket(client, token, project["id"], summary="In sprint", sprint_id=sprint["id"])

    # Default board (no sprint_id) follows the active sprint
    board = client.get(f"/api/v1/projects/{project['id']}/board", headers=auth_headers(token)).json()
    board_ticket_ids = {t["id"] for t in board["tickets"]}
    assert sprint_ticket["id"] in board_ticket_ids
    assert backlog_ticket["id"] not in board_ticket_ids
    assert [s["name"] for s in board["statuses"]] == [s["name"] for s in statuses]
    assert board["sprint"]["id"] == sprint["id"]


def test_ticket_position_reorders_within_and_across_columns(client, db_session):
    company = create_company(db_session)
    _, _, token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    project = _create_project(client, token)
    statuses = client.get(f"/api/v1/projects/{project['id']}/statuses", headers=auth_headers(token)).json()
    todo = next(s for s in statuses if s["name"] == "To Do")
    in_progress = next(s for s in statuses if s["name"] == "In Progress")

    t1 = _create_ticket(client, token, project["id"], summary="First")
    t2 = _create_ticket(client, token, project["id"], summary="Second")
    assert t1["board_position"] == 0
    assert t2["board_position"] == 1

    # Move t2 to the front of the To Do column
    resp = client.post(
        f"/api/v1/tickets/{t2['id']}/position", json={"status_id": todo["id"], "position": 0}, headers=auth_headers(token)
    )
    assert resp.status_code == 200
    t1_after = client.get(f"/api/v1/tickets/{t1['id']}", headers=auth_headers(token)).json()
    t2_after = client.get(f"/api/v1/tickets/{t2['id']}", headers=auth_headers(token)).json()
    assert t2_after["board_position"] < t1_after["board_position"]

    # Move t1 into the In Progress column - this is also a status transition
    resp2 = client.post(
        f"/api/v1/tickets/{t1['id']}/position", json={"status_id": in_progress["id"], "position": 0},
        headers=auth_headers(token),
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"]["id"] == in_progress["id"]

    activities = client.get(f"/api/v1/tickets/{t1['id']}/activities", headers=auth_headers(token)).json()
    assert any(a["action"] == "transitioned" for a in activities)


def test_backlog_endpoint_sections_tickets_by_sprint(client, db_session):
    company = create_company(db_session)
    _, _, token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    project = _create_project(client, token)

    backlog_ticket = _create_ticket(client, token, project["id"], summary="Unplanned")
    future_sprint = client.post(
        f"/api/v1/projects/{project['id']}/sprints", json={"name": "Sprint 2"}, headers=auth_headers(token)
    ).json()
    future_ticket = _create_ticket(client, token, project["id"], summary="Planned", sprint_id=future_sprint["id"])

    backlog = client.get(f"/api/v1/projects/{project['id']}/backlog", headers=auth_headers(token)).json()
    assert backlog["active_sprint"] is None
    assert {t["id"] for t in backlog["backlog_tickets"]} == {backlog_ticket["id"]}
    assert [s["id"] for s in backlog["future_sprints"]] == [future_sprint["id"]]
    future_tickets = backlog["future_sprint_tickets"][str(future_sprint["id"])]
    assert {t["id"] for t in future_tickets} == {future_ticket["id"]}


def test_bulk_update_status_and_delete(client, db_session):
    company = create_company(db_session)
    _, _, token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    project = _create_project(client, token)
    statuses = client.get(f"/api/v1/projects/{project['id']}/statuses", headers=auth_headers(token)).json()
    done = next(s for s in statuses if s["name"] == "Done")

    t1 = _create_ticket(client, token, project["id"], summary="One")
    t2 = _create_ticket(client, token, project["id"], summary="Two")

    bulk_resp = client.post(
        "/api/v1/tickets/bulk",
        json={"ticket_ids": [t1["id"], t2["id"]], "status_id": done["id"]},
        headers=auth_headers(token),
    )
    assert bulk_resp.status_code == 200
    assert bulk_resp.json()["updated_count"] == 2

    t1_after = client.get(f"/api/v1/tickets/{t1['id']}", headers=auth_headers(token)).json()
    assert t1_after["status"]["id"] == done["id"]
    assert t1_after["resolved_at"] is not None

    delete_resp = client.post(
        "/api/v1/tickets/bulk", json={"ticket_ids": [t1["id"], t2["id"]], "delete": True}, headers=auth_headers(token)
    )
    assert delete_resp.status_code == 200
    assert delete_resp.json()["updated_count"] == 2

    remaining = client.get("/api/v1/tickets", params={"project_id": project["id"]}, headers=auth_headers(token)).json()
    assert remaining == []
