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


def test_labels_crud_and_ticket_assignment(client, db_session):
    company = create_company(db_session)
    _, _, token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    project = _create_project(client, token)
    ticket = _create_ticket(client, token, project["id"])

    create_resp = client.post(
        f"/api/v1/projects/{project['id']}/labels", json={"name": "urgent", "color": "#dc3545"}, headers=auth_headers(token)
    )
    assert create_resp.status_code == 201, create_resp.text
    label = create_resp.json()

    assign_resp = client.post(
        f"/api/v1/tickets/{ticket['id']}/labels", json={"label_id": label["id"]}, headers=auth_headers(token)
    )
    assert assign_resp.status_code == 200
    assert [lbl["name"] for lbl in assign_resp.json()["labels"]] == ["urgent"]

    list_resp = client.get(f"/api/v1/tickets/{ticket['id']}", headers=auth_headers(token))
    assert [lbl["name"] for lbl in list_resp.json()["labels"]] == ["urgent"]

    remove_resp = client.delete(f"/api/v1/tickets/{ticket['id']}/labels/{label['id']}", headers=auth_headers(token))
    assert remove_resp.status_code == 200
    assert remove_resp.json()["labels"] == []

    delete_label_resp = client.delete(f"/api/v1/projects/{project['id']}/labels/{label['id']}", headers=auth_headers(token))
    assert delete_label_resp.status_code == 204


def test_project_watch_and_unwatch(client, db_session):
    company = create_company(db_session)
    _, _, token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    project = _create_project(client, token)

    detail = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(token)).json()
    assert detail["is_watching"] is False

    watch_resp = client.post(f"/api/v1/projects/{project['id']}/watch", headers=auth_headers(token))
    assert watch_resp.status_code == 204
    detail_after = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(token)).json()
    assert detail_after["is_watching"] is True

    unwatch_resp = client.delete(f"/api/v1/projects/{project['id']}/watch", headers=auth_headers(token))
    assert unwatch_resp.status_code == 204
    detail_final = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(token)).json()
    assert detail_final["is_watching"] is False


def test_time_tracking_log_work_and_report(client, db_session):
    company = create_company(db_session)
    _, _, token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    project = _create_project(client, token)
    ticket = _create_ticket(client, token, project["id"], original_estimate=120)

    log_resp = client.post(
        f"/api/v1/tickets/{ticket['id']}/worklogs",
        json={"minutes_spent": 45, "log_date": "2026-01-05", "description": "Investigated the issue"},
        headers=auth_headers(token),
    )
    assert log_resp.status_code == 201, log_resp.text
    updated_ticket = log_resp.json()
    assert updated_ticket["time_spent"] == 45
    assert updated_ticket["remaining_estimate"] == 75

    worklogs = client.get(f"/api/v1/tickets/{ticket['id']}/worklogs", headers=auth_headers(token)).json()
    assert len(worklogs) == 1
    assert worklogs[0]["minutes_spent"] == 45

    report = client.get("/api/v1/tickets/time-report", params={"project_id": project["id"]}, headers=auth_headers(token)).json()
    assert report["entries"][0]["total_minutes"] == 45
    assert report["entries"][0]["ticket_breakdown"][ticket["ticket_key"]] == 45


def test_ticket_export_csv_and_json(client, db_session):
    company = create_company(db_session)
    _, _, token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    project = _create_project(client, token)
    _create_ticket(client, token, project["id"], summary="Export me")

    csv_resp = client.get("/api/v1/tickets/export", params={"project_id": project["id"]}, headers=auth_headers(token))
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert "Export me" in csv_resp.text

    json_resp = client.get(
        "/api/v1/tickets/export", params={"project_id": project["id"], "format": "json"}, headers=auth_headers(token)
    )
    assert json_resp.status_code == 200
    assert json_resp.json()[0]["summary"] == "Export me"


def test_viewer_role_cannot_mutate_but_can_read(client, db_session):
    company = create_company(db_session)
    _, _, admin_token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    _, viewer_employee, viewer_token = _setup_user_and_employee(client, db_session, company, "guest@example.com", "EMP-002")
    project = _create_project(client, admin_token)

    # Not a project member -> defaults to viewer: can read, cannot create
    board = client.get(f"/api/v1/projects/{project['id']}/board", headers=auth_headers(viewer_token))
    assert board.status_code == 200

    issue_types = client.get("/api/v1/issue-types", headers=auth_headers(viewer_token)).json()
    create_resp = client.post(
        "/api/v1/tickets",
        json={"project_id": project["id"], "summary": "Should fail", "issue_type_id": issue_types[0]["id"]},
        headers=auth_headers(viewer_token),
    )
    assert create_resp.status_code == 403

    # Explicitly added as a "viewer" project member -> still blocked
    add_member_resp = client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"employee_id": viewer_employee.id, "role": "viewer"},
        headers=auth_headers(admin_token),
    )
    assert add_member_resp.status_code == 201
    create_resp_2 = client.post(
        "/api/v1/tickets",
        json={"project_id": project["id"], "summary": "Should still fail", "issue_type_id": issue_types[0]["id"]},
        headers=auth_headers(viewer_token),
    )
    assert create_resp_2.status_code == 403


def test_developer_can_create_but_not_delete_others_tickets(client, db_session):
    company = create_company(db_session)
    _, admin_employee, admin_token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    _, dev_employee, dev_token = _setup_user_and_employee(client, db_session, company, "dev@example.com", "EMP-002")
    project = _create_project(client, admin_token)
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"employee_id": dev_employee.id, "role": "developer"},
        headers=auth_headers(admin_token),
    )

    ticket = _create_ticket(client, admin_token, project["id"], summary="Admin's ticket")

    issue_types = client.get("/api/v1/issue-types", headers=auth_headers(dev_token)).json()
    dev_create = client.post(
        "/api/v1/tickets",
        json={"project_id": project["id"], "summary": "Dev's own ticket", "issue_type_id": issue_types[0]["id"]},
        headers=auth_headers(dev_token),
    )
    assert dev_create.status_code == 201

    # Developer cannot delete a ticket reported by someone else
    delete_resp = client.delete(f"/api/v1/tickets/{ticket['id']}", headers=auth_headers(dev_token))
    assert delete_resp.status_code == 403

    # Developer cannot edit a ticket they neither reported nor are assigned to
    edit_resp = client.put(
        f"/api/v1/tickets/{ticket['id']}", json={"summary": "Hijacked"}, headers=auth_headers(dev_token)
    )
    assert edit_resp.status_code == 403

    # But a developer CAN edit their own (reported) ticket
    own_ticket = dev_create.json()
    own_edit = client.put(
        f"/api/v1/tickets/{own_ticket['id']}", json={"summary": "Updated by dev"}, headers=auth_headers(dev_token)
    )
    assert own_edit.status_code == 200

    # Sanity: the admin's project role is reported correctly
    assert admin_employee.id != dev_employee.id
    project_detail = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(admin_token)).json()
    assert project_detail["my_role"] == "admin"


def test_project_member_role_update(client, db_session):
    company = create_company(db_session)
    _, _, admin_token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    _, dev_employee, dev_token = _setup_user_and_employee(client, db_session, company, "dev@example.com", "EMP-002")
    project = _create_project(client, admin_token)

    add_resp = client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"employee_id": dev_employee.id, "role": "developer"},
        headers=auth_headers(admin_token),
    )
    member_id = add_resp.json()["id"]

    promote_resp = client.put(
        f"/api/v1/projects/{project['id']}/members/{member_id}", json={"role": "manager"}, headers=auth_headers(admin_token)
    )
    assert promote_resp.status_code == 200
    assert promote_resp.json()["role"] == "manager"

    project_detail = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(dev_token)).json()
    assert project_detail["my_role"] == "manager"

    # A non-admin (manager) cannot promote/demote other members
    other_resp = client.put(
        f"/api/v1/projects/{project['id']}/members/{member_id}", json={"role": "viewer"}, headers=auth_headers(dev_token)
    )
    assert other_resp.status_code == 403
