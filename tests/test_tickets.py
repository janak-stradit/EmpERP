from app.models.employee import Employee
from app.models.user import UserRole
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


def _setup_user_and_employee(client, db_session, company, email, employee_code, role=UserRole.EMPLOYEE):
    user = create_user(db_session, company, email, "Password123!", role=role, full_name=email.split("@")[0])
    employee = _create_employee(db_session, company, user, employee_code)
    token = login(client, email, "Password123!")
    return user, employee, token


def _create_project(client, token, key="DEV", name="Development"):
    resp = client.post("/api/v1/projects", json={"key": key, "name": name}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_project_creation_seeds_default_statuses_and_catalog(client, db_session):
    company = create_company(db_session)
    _, _, token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")

    project = _create_project(client, token)
    assert project["key"] == "DEV"
    assert project["open_ticket_count"] == 0

    statuses = client.get(f"/api/v1/projects/{project['id']}/statuses", headers=auth_headers(token)).json()
    assert [s["name"] for s in statuses] == ["To Do", "In Progress", "Done"]
    assert statuses[0]["is_default"] is True

    issue_types = client.get("/api/v1/issue-types", headers=auth_headers(token)).json()
    assert {t["name"] for t in issue_types} == {"Bug", "Task", "Story", "Epic", "Sub-task"}

    priorities = client.get("/api/v1/priorities", headers=auth_headers(token)).json()
    assert {p["name"] for p in priorities} == {"Highest", "High", "Medium", "Low", "Lowest"}


def test_duplicate_project_key_rejected(client, db_session):
    company = create_company(db_session)
    _, _, token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    _create_project(client, token, key="DEV")

    resp = client.post("/api/v1/projects", json={"key": "dev", "name": "Duplicate"}, headers=auth_headers(token))
    assert resp.status_code == 400


def test_ticket_lifecycle_create_transition_comment_activity(client, db_session):
    company = create_company(db_session)
    _, reporter_employee, reporter_token = _setup_user_and_employee(
        client, db_session, company, "reporter@example.com", "EMP-001"
    )
    assignee_user, assignee_employee, _ = _setup_user_and_employee(
        client, db_session, company, "assignee@example.com", "EMP-002"
    )
    project = _create_project(client, reporter_token)
    issue_types = client.get("/api/v1/issue-types", headers=auth_headers(reporter_token)).json()
    bug_type = next(t for t in issue_types if t["name"] == "Bug")

    create_resp = client.post(
        "/api/v1/tickets",
        json={
            "project_id": project["id"],
            "summary": "Login button broken",
            "issue_type_id": bug_type["id"],
            "assignee_id": assignee_employee.id,
        },
        headers=auth_headers(reporter_token),
    )
    assert create_resp.status_code == 201, create_resp.text
    ticket = create_resp.json()
    assert ticket["ticket_key"] == "DEV-001"
    assert ticket["status"]["name"] == "To Do"
    assert ticket["reporter_id"] == reporter_employee.id
    assert ticket["assignee_id"] == assignee_employee.id

    # A second ticket increments the per-project sequence independently of other projects.
    create_resp_2 = client.post(
        "/api/v1/tickets",
        json={"project_id": project["id"], "summary": "Second issue", "issue_type_id": bug_type["id"]},
        headers=auth_headers(reporter_token),
    )
    assert create_resp_2.json()["ticket_key"] == "DEV-002"

    # Comment
    comment_resp = client.post(
        f"/api/v1/tickets/{ticket['id']}/comments",
        json={"body": "Investigating now"},
        headers=auth_headers(reporter_token),
    )
    assert comment_resp.status_code == 201, comment_resp.text

    # Transition to "In Progress" then "Done"
    statuses = client.get(f"/api/v1/projects/{project['id']}/statuses", headers=auth_headers(reporter_token)).json()
    in_progress = next(s for s in statuses if s["name"] == "In Progress")
    done = next(s for s in statuses if s["name"] == "Done")

    transition_resp = client.post(
        f"/api/v1/tickets/{ticket['id']}/transition",
        json={"status_id": in_progress["id"]},
        headers=auth_headers(reporter_token),
    )
    assert transition_resp.status_code == 200
    assert transition_resp.json()["resolved_at"] is None

    done_resp = client.post(
        f"/api/v1/tickets/{ticket['id']}/transition",
        json={"status_id": done["id"]},
        headers=auth_headers(reporter_token),
    )
    assert done_resp.status_code == 200
    assert done_resp.json()["resolved_at"] is not None

    # Activity trail captures created, commented, and two transitions
    activities = client.get(f"/api/v1/tickets/{ticket['id']}/activities", headers=auth_headers(reporter_token)).json()
    actions = [a["action"] for a in activities]
    assert actions.count("created") == 1
    assert actions.count("commented") == 1
    assert actions.count("transitioned") == 2

    # Soft delete hides the ticket from listings
    delete_resp = client.delete(f"/api/v1/tickets/{ticket['id']}", headers=auth_headers(reporter_token))
    assert delete_resp.status_code == 204
    list_resp = client.get("/api/v1/tickets", params={"project_id": project["id"]}, headers=auth_headers(reporter_token))
    remaining_keys = {t["ticket_key"] for t in list_resp.json()}
    assert "DEV-001" not in remaining_keys
    assert "DEV-002" in remaining_keys


def test_ticket_search_and_filters(client, db_session):
    company = create_company(db_session)
    _, _, token = _setup_user_and_employee(client, db_session, company, "reporter@example.com", "EMP-001")
    project = _create_project(client, token)
    issue_types = client.get("/api/v1/issue-types", headers=auth_headers(token)).json()
    bug_type = next(t for t in issue_types if t["name"] == "Bug")
    task_type = next(t for t in issue_types if t["name"] == "Task")

    client.post(
        "/api/v1/tickets",
        json={"project_id": project["id"], "summary": "Crash on save", "issue_type_id": bug_type["id"]},
        headers=auth_headers(token),
    )
    client.post(
        "/api/v1/tickets",
        json={"project_id": project["id"], "summary": "Write onboarding docs", "issue_type_id": task_type["id"]},
        headers=auth_headers(token),
    )

    search_resp = client.get(
        "/api/v1/tickets", params={"project_id": project["id"], "q": "crash"}, headers=auth_headers(token)
    )
    assert [t["summary"] for t in search_resp.json()] == ["Crash on save"]

    type_resp = client.get(
        "/api/v1/tickets",
        params={"project_id": project["id"], "issue_type_id": task_type["id"]},
        headers=auth_headers(token),
    )
    assert [t["summary"] for t in type_resp.json()] == ["Write onboarding docs"]


def test_comment_edit_permissions(client, db_session):
    company = create_company(db_session)
    _, _, token_a = _setup_user_and_employee(client, db_session, company, "a@example.com", "EMP-001")
    _, _, token_b = _setup_user_and_employee(client, db_session, company, "b@example.com", "EMP-002")
    project = _create_project(client, token_a)
    issue_types = client.get("/api/v1/issue-types", headers=auth_headers(token_a)).json()
    bug_type = issue_types[0]

    ticket = client.post(
        "/api/v1/tickets",
        json={"project_id": project["id"], "summary": "Something broke", "issue_type_id": bug_type["id"]},
        headers=auth_headers(token_a),
    ).json()

    comment = client.post(
        f"/api/v1/tickets/{ticket['id']}/comments", json={"body": "Original"}, headers=auth_headers(token_a)
    ).json()

    # Another user cannot edit someone else's comment
    resp = client.put(
        f"/api/v1/tickets/{ticket['id']}/comments/{comment['id']}",
        json={"body": "Hijacked"},
        headers=auth_headers(token_b),
    )
    assert resp.status_code == 403

    # Author can edit their own comment
    resp = client.put(
        f"/api/v1/tickets/{ticket['id']}/comments/{comment['id']}",
        json={"body": "Edited"},
        headers=auth_headers(token_a),
    )
    assert resp.status_code == 200
    assert resp.json()["body"] == "Edited"


def test_watchers_auto_added_for_reporter_and_assignee(client, db_session):
    company = create_company(db_session)
    _, _, reporter_token = _setup_user_and_employee(
        client, db_session, company, "reporter@example.com", "EMP-001"
    )
    _, assignee_employee, _ = _setup_user_and_employee(client, db_session, company, "assignee@example.com", "EMP-002")
    project = _create_project(client, reporter_token)
    issue_types = client.get("/api/v1/issue-types", headers=auth_headers(reporter_token)).json()

    ticket = client.post(
        "/api/v1/tickets",
        json={
            "project_id": project["id"],
            "summary": "Watch me",
            "issue_type_id": issue_types[0]["id"],
            "assignee_id": assignee_employee.id,
        },
        headers=auth_headers(reporter_token),
    ).json()

    detail = client.get(f"/api/v1/tickets/{ticket['id']}", headers=auth_headers(reporter_token)).json()
    assert detail["watcher_count"] == 2
    assert detail["is_watching"] is True
