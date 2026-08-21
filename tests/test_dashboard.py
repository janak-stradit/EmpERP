from datetime import date, timedelta

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


def test_dashboard_kpis_and_workload(client, db_session):
    company = create_company(db_session)
    _, reporter, token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    _, assignee, _ = _setup_user_and_employee(client, db_session, company, "dev@example.com", "EMP-002")
    project = _create_project(client, token)
    statuses = client.get(f"/api/v1/projects/{project['id']}/statuses", headers=auth_headers(token)).json()
    in_progress = next(s for s in statuses if s["name"] == "In Progress")
    done = next(s for s in statuses if s["name"] == "Done")

    open_ticket = _create_ticket(client, token, project["id"], summary="Open one", assignee_id=assignee.id, story_points=3)
    overdue_ticket = _create_ticket(
        client, token, project["id"], summary="Overdue one", assignee_id=assignee.id,
        due_date=(date.today() - timedelta(days=2)).isoformat(),
    )
    in_progress_ticket = _create_ticket(client, token, project["id"], summary="Doing", assignee_id=reporter.id)
    client.post(
        f"/api/v1/tickets/{in_progress_ticket['id']}/transition", json={"status_id": in_progress["id"]}, headers=auth_headers(token)
    )
    done_ticket = _create_ticket(client, token, project["id"], summary="Done one", assignee_id=reporter.id)
    client.post(f"/api/v1/tickets/{done_ticket['id']}/transition", json={"status_id": done["id"]}, headers=auth_headers(token))

    dashboard = client.get(f"/api/v1/dashboard/{project['id']}", headers=auth_headers(token)).json()

    assert dashboard["kpis"]["open"]["value"] == 3  # open_ticket, overdue_ticket, in_progress_ticket
    assert dashboard["kpis"]["in_progress"]["value"] == 1
    assert dashboard["kpis"]["completed_this_week"]["value"] == 1
    assert dashboard["kpis"]["overdue"]["value"] == 1

    status_names = {s["name"]: s["count"] for s in dashboard["status_distribution"]}
    assert status_names["Done"] == 1
    assert status_names["In Progress"] == 1

    workload_by_name = {w["employee_name"]: w for w in dashboard["workload_distribution"]}
    assert workload_by_name["dev"]["open_count"] == 2
    assert workload_by_name["dev"]["overdue_count"] == 1
    assert workload_by_name["dev"]["total_points"] == 3

    # My open tickets for the reporter (who is assigned the in-progress ticket)
    my_keys = {t["ticket_key"] for t in dashboard["my_open_tickets"]}
    assert in_progress_ticket["ticket_key"] in my_keys
    assert done_ticket["ticket_key"] not in my_keys

    # Recent activity should include the creations and the two transitions
    actions = [a["action"] for a in dashboard["recent_activity"]]
    assert "created" in actions
    assert "transitioned" in actions

    assert dashboard["sprint_progress"] is None

    # Ids referenced above stay used for readability of the test intent
    assert open_ticket["status"]["name"] == "To Do"
    assert overdue_ticket["due_date"] is not None


def test_dashboard_resolution_buckets_and_creation_trend(client, db_session):
    company = create_company(db_session)
    _, _, token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    project = _create_project(client, token)
    statuses = client.get(f"/api/v1/projects/{project['id']}/statuses", headers=auth_headers(token)).json()
    done = next(s for s in statuses if s["name"] == "Done")

    t = _create_ticket(client, token, project["id"], summary="Quick fix")
    client.post(f"/api/v1/tickets/{t['id']}/transition", json={"status_id": done["id"]}, headers=auth_headers(token))

    dashboard = client.get(f"/api/v1/dashboard/{project['id']}", headers=auth_headers(token)).json()
    bucket_counts = {b["label"]: b["count"] for b in dashboard["resolution_time_buckets"]}
    assert bucket_counts["0-1 day"] == 1

    trend_total = sum(p["count"] for p in dashboard["creation_trend"])
    assert trend_total == 1
    assert len(dashboard["creation_trend"]) == 30


def test_burndown_and_velocity_and_sprint_report(client, db_session):
    company = create_company(db_session)
    _, _, token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    project = _create_project(client, token)
    statuses = client.get(f"/api/v1/projects/{project['id']}/statuses", headers=auth_headers(token)).json()
    done = next(s for s in statuses if s["name"] == "Done")

    sprint = client.post(
        f"/api/v1/projects/{project['id']}/sprints",
        json={
            "name": "Sprint 1",
            "start_date": (date.today() - timedelta(days=3)).isoformat(),
            "end_date": (date.today() + timedelta(days=3)).isoformat(),
        },
        headers=auth_headers(token),
    ).json()

    t1 = _create_ticket(client, token, project["id"], summary="A", sprint_id=sprint["id"], story_points=5)
    _create_ticket(client, token, project["id"], summary="B", sprint_id=sprint["id"], story_points=3)

    client.post(f"/api/v1/sprints/{sprint['id']}/start", headers=auth_headers(token))
    client.post(f"/api/v1/tickets/{t1['id']}/transition", json={"status_id": done["id"]}, headers=auth_headers(token))

    burndown = client.get(f"/api/v1/dashboard/{project['id']}/burndown", headers=auth_headers(token)).json()
    assert burndown["total_points"] == 8
    assert burndown["points"][-1]["ideal"] == 0
    today_point = next(p for p in burndown["points"] if p["date"] == date.today().isoformat())
    assert today_point["actual"] == 3  # 8 committed - 5 resolved

    client.post(f"/api/v1/sprints/{sprint['id']}/complete", json={"incomplete_action": "backlog"}, headers=auth_headers(token))

    velocity = client.get(f"/api/v1/dashboard/{project['id']}/velocity", headers=auth_headers(token)).json()
    assert len(velocity["sprints"]) == 1
    assert velocity["sprints"][0]["committed_points"] == 8
    assert velocity["sprints"][0]["completed_points"] == 5

    report = client.get(f"/api/v1/reports/sprint/{sprint['id']}", headers=auth_headers(token)).json()
    assert report["committed_points"] == 8
    assert report["completed_points"] == 5
    assert {t["ticket_key"] for t in report["completed_tickets"]} == {t1["ticket_key"]}
    # t2 moved to the backlog on completion, so it's no longer associated with this sprint
    assert report["incomplete_tickets"] == []


def test_velocity_and_sprint_report_include_linked_project_tickets(client, db_session):
    company = create_company(db_session)
    _, _, token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    project_a = _create_project(client, token, key="DEV")
    project_b = _create_project(client, token, key="OPS")
    statuses_b = client.get(f"/api/v1/projects/{project_b['id']}/statuses", headers=auth_headers(token)).json()
    done_b = next(s for s in statuses_b if s["name"] == "Done")

    sprint = client.post(
        f"/api/v1/projects/{project_a['id']}/sprints",
        json={"name": "Shared Sprint", "linked_project_ids": [project_b["id"]]},
        headers=auth_headers(token),
    ).json()

    t_a = _create_ticket(client, token, project_a["id"], summary="A", sprint_id=sprint["id"], story_points=5)
    t_b = _create_ticket(client, token, project_b["id"], summary="B", sprint_id=sprint["id"], story_points=3)

    client.post(f"/api/v1/sprints/{sprint['id']}/start", headers=auth_headers(token))
    # Complete the project B ticket using project B's own "Done" status.
    client.post(f"/api/v1/tickets/{t_b['id']}/transition", json={"status_id": done_b["id"]}, headers=auth_headers(token))
    client.post(f"/api/v1/sprints/{sprint['id']}/complete", json={"incomplete_action": "backlog"}, headers=auth_headers(token))

    velocity = client.get(f"/api/v1/dashboard/{project_a['id']}/velocity", headers=auth_headers(token)).json()
    assert len(velocity["sprints"]) == 1
    assert velocity["sprints"][0]["committed_points"] == 8
    assert velocity["sprints"][0]["completed_points"] == 3  # only the project B ticket was marked done

    report = client.get(f"/api/v1/reports/sprint/{sprint['id']}", headers=auth_headers(token)).json()
    assert report["completed_points"] == 3
    assert {t["ticket_key"] for t in report["completed_tickets"]} == {t_b["ticket_key"]}
    assert {t["project_key"] for t in report["completed_tickets"]} == {"OPS"}
    # t_a moved to the backlog on completion since it was never marked done.
    assert report["incomplete_tickets"] == []


def test_workload_report_export_csv(client, db_session):
    company = create_company(db_session)
    _, _, token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    project = _create_project(client, token)
    _create_ticket(client, token, project["id"], summary="Something")

    resp = client.get(f"/api/v1/reports/workload/export?project_id={project['id']}", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "Member" in resp.text


def test_global_dashboard_aggregates_across_projects(client, db_session):
    company = create_company(db_session)
    _, reporter, token = _setup_user_and_employee(client, db_session, company, "lead@example.com", "EMP-001")
    _, assignee, _ = _setup_user_and_employee(client, db_session, company, "dev@example.com", "EMP-002")
    project_a = _create_project(client, token, key="ALPHA")
    project_b = _create_project(client, token, key="BETA")

    statuses_a = client.get(f"/api/v1/projects/{project_a['id']}/statuses", headers=auth_headers(token)).json()
    done_a = next(s for s in statuses_a if s["name"] == "Done")

    _create_ticket(client, token, project_a["id"], summary="Alpha open", assignee_id=assignee.id, story_points=2)
    ticket_a_done = _create_ticket(client, token, project_a["id"], summary="Alpha done")
    client.post(f"/api/v1/tickets/{ticket_a_done['id']}/transition", json={"status_id": done_a["id"]}, headers=auth_headers(token))
    _create_ticket(client, token, project_b["id"], summary="Beta open", assignee_id=reporter.id)

    sprint = client.post(
        f"/api/v1/projects/{project_a['id']}/sprints", json={"name": "Sprint 1"}, headers=auth_headers(token)
    ).json()
    client.post(f"/api/v1/sprints/{sprint['id']}/start", headers=auth_headers(token))

    dashboard = client.get("/api/v1/dashboard", headers=auth_headers(token)).json()

    # Open count spans both projects; the one Done ticket in ALPHA is excluded.
    assert dashboard["kpis"]["open"]["value"] == 2

    category_counts = {c["category"]: c["count"] for c in dashboard["category_distribution"]}
    assert category_counts["done"] == 1
    assert category_counts["todo"] == 2

    breakdown_by_key = {p["project_key"]: p for p in dashboard["project_breakdown"]}
    assert breakdown_by_key["ALPHA"]["open_count"] == 1
    assert breakdown_by_key["BETA"]["open_count"] == 1

    active_sprint_projects = {s["project_key"] for s in dashboard["active_sprints"]}
    assert active_sprint_projects == {"ALPHA"}

    workload_by_name = {w["employee_name"]: w for w in dashboard["workload_distribution"]}
    assert workload_by_name["dev"]["open_count"] == 1
    assert workload_by_name["lead"]["open_count"] == 1
