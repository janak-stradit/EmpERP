from app.models.user import UserRole
from tests.helpers import auth_headers, create_company, create_user, login


def _create_employee(client, hr_token, email="alice@example.com"):
    resp = client.post(
        "/api/v1/employees",
        json={
            "email": email,
            "full_name": "Alice Example",
            "initial_password": "InitialPass123!",
            "role": "employee",
            "joining_date": "2026-01-01",
        },
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_template_with_task(client, hr_token):
    resp = client.post(
        "/api/v1/onboarding/templates",
        json={"name": "Standard Onboarding", "description": "Default checklist"},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 201, resp.text
    template_id = resp.json()["id"]

    resp = client.post(
        f"/api/v1/onboarding/templates/{template_id}/tasks",
        json={"title": "Submit ID proof", "assigned_to_role": "employee", "due_days": 3},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 201, resp.text
    return template_id


def test_assign_and_complete_onboarding_updates_progress(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    employee = _create_employee(client, hr_token)
    template_id = _create_template_with_task(client, hr_token)

    resp = client.post(
        "/api/v1/onboarding/assign",
        json={"employee_id": employee["id"], "template_id": template_id},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 201, resp.text
    onboarding = resp.json()
    assert onboarding["progress_percent"] == 0.0
    assert onboarding["status"] == "in_progress"
    task_id = onboarding["tasks"][0]["id"]

    employee_token = login(client, "alice@example.com", "InitialPass123!")
    resp = client.put(
        f"/api/v1/onboarding/tasks/{task_id}",
        json={"status": "completed"},
        headers=auth_headers(employee_token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    resp = client.get(f"/api/v1/onboarding/employee/{employee['id']}", headers=auth_headers(hr_token))
    assert resp.status_code == 200
    data = resp.json()[0]
    assert data["progress_percent"] == 100.0
    assert data["status"] == "completed"


def test_other_employee_cannot_update_task_status(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    employee = _create_employee(client, hr_token, email="alice@example.com")
    _create_employee(client, hr_token, email="mallory@example.com")
    template_id = _create_template_with_task(client, hr_token)

    resp = client.post(
        "/api/v1/onboarding/assign",
        json={"employee_id": employee["id"], "template_id": template_id},
        headers=auth_headers(hr_token),
    )
    task_id = resp.json()["tasks"][0]["id"]

    mallory_token = login(client, "mallory@example.com", "InitialPass123!")
    resp = client.put(
        f"/api/v1/onboarding/tasks/{task_id}",
        json={"status": "completed"},
        headers=auth_headers(mallory_token),
    )
    assert resp.status_code == 403
