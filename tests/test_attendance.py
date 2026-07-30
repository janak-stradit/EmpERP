from datetime import date

from app.models.user import UserRole
from tests.helpers import auth_headers, create_company, create_user, login


def _create_employee(client, hr_token, email, full_name="Test Employee", manager_id=None):
    payload = {
        "email": email,
        "full_name": full_name,
        "initial_password": "InitialPass123!",
        "role": "employee",
        "joining_date": "2026-01-01",
    }
    if manager_id is not None:
        payload["reporting_manager_id"] = manager_id
    resp = client.post("/api/v1/employees", json=payload, headers=auth_headers(hr_token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_clock_in_and_out_happy_path(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, "alice@example.com")
    employee_token = login(client, "alice@example.com", "InitialPass123!")

    resp = client.get("/api/v1/attendance/today/me", headers=auth_headers(employee_token))
    assert resp.status_code == 200
    assert resp.json()["clocked_in"] is False

    resp = client.post("/api/v1/attendance/clock-in", json={}, headers=auth_headers(employee_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] in ("present", "late", "half_day")
    assert resp.json()["clock_out"] is None

    resp = client.post("/api/v1/attendance/clock-out", json={}, headers=auth_headers(employee_token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["clock_out"] is not None
    assert data["work_hours"] is not None
    assert data["work_hours"] >= 0


def test_cannot_clock_in_twice(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, "bob@example.com")
    employee_token = login(client, "bob@example.com", "InitialPass123!")

    resp = client.post("/api/v1/attendance/clock-in", json={}, headers=auth_headers(employee_token))
    assert resp.status_code == 200

    resp = client.post("/api/v1/attendance/clock-in", json={}, headers=auth_headers(employee_token))
    assert resp.status_code == 400


def test_cannot_clock_out_without_clock_in(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, "carol@example.com")
    employee_token = login(client, "carol@example.com", "InitialPass123!")

    resp = client.post("/api/v1/attendance/clock-out", json={}, headers=auth_headers(employee_token))
    assert resp.status_code == 400


def test_shift_management_requires_hr_role(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, "dave@example.com")
    employee_token = login(client, "dave@example.com", "InitialPass123!")

    resp = client.post(
        "/api/v1/attendance/shifts",
        json={"name": "General Shift", "start_time": "09:00:00", "end_time": "18:00:00"},
        headers=auth_headers(employee_token),
    )
    assert resp.status_code == 403

    resp = client.post(
        "/api/v1/attendance/shifts",
        json={"name": "General Shift", "start_time": "09:00:00", "end_time": "18:00:00"},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 201, resp.text


def test_regularization_request_and_approval_upserts_log(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, "erin@example.com")
    employee_token = login(client, "erin@example.com", "InitialPass123!")

    resp = client.post(
        "/api/v1/attendance/regularizations",
        json={
            "date": "2026-03-02",
            "requested_clock_in": "2026-03-02T09:05:00Z",
            "requested_clock_out": "2026-03-02T18:10:00Z",
            "reason": "Forgot to punch in",
        },
        headers=auth_headers(employee_token),
    )
    assert resp.status_code == 201, resp.text
    reg_id = resp.json()["id"]
    assert resp.json()["status"] == "pending"

    resp = client.post(
        f"/api/v1/attendance/regularizations/{reg_id}/action",
        json={"action": "approve"},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"

    resp = client.get(
        "/api/v1/attendance/me?from=2026-03-01&to=2026-03-03", headers=auth_headers(employee_token)
    )
    assert resp.status_code == 200
    logs = resp.json()
    assert len(logs) == 1
    assert logs[0]["date"] == "2026-03-02"
    assert logs[0]["status"] == "present"
    assert logs[0]["work_hours"] is not None


def test_manager_can_approve_reports_regularization_but_not_others(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    manager1 = _create_employee(client, hr_token, "manager1@example.com", full_name="Manager One")
    _create_employee(client, hr_token, "manager2@example.com", full_name="Manager Two")
    _create_employee(client, hr_token, "frank@example.com", manager_id=manager1["id"])

    manager2_token = login(client, "manager2@example.com", "InitialPass123!")
    employee_token = login(client, "frank@example.com", "InitialPass123!")

    resp = client.post(
        "/api/v1/attendance/regularizations",
        json={"date": "2026-03-05", "reason": "Missed punch"},
        headers=auth_headers(employee_token),
    )
    reg_id = resp.json()["id"]

    resp = client.post(
        f"/api/v1/attendance/regularizations/{reg_id}/action",
        json={"action": "approve"},
        headers=auth_headers(manager2_token),
    )
    assert resp.status_code == 403


def test_attendance_report_requires_hr_role(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, "grace@example.com")
    employee_token = login(client, "grace@example.com", "InitialPass123!")

    resp = client.get(
        "/api/v1/attendance/report?from=2026-01-01&to=2026-12-31", headers=auth_headers(employee_token)
    )
    assert resp.status_code == 403

    resp = client.get(
        "/api/v1/attendance/report?from=2026-01-01&to=2026-12-31", headers=auth_headers(hr_token)
    )
    assert resp.status_code == 200
