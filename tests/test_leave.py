from app.models.user import UserRole
from tests.helpers import auth_headers, create_company, create_user, login


def _create_employee(client, hr_token, email, full_name="Test Employee", role="employee", manager_id=None):
    payload = {
        "email": email,
        "full_name": full_name,
        "initial_password": "InitialPass123!",
        "role": role,
        "joining_date": "2026-01-01",
    }
    if manager_id is not None:
        payload["reporting_manager_id"] = manager_id
    resp = client.post("/api/v1/employees", json=payload, headers=auth_headers(hr_token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_leave_type(client, hr_token, name="Casual Leave", code="CL", max_days=12, is_unpaid=False):
    resp = client.post(
        "/api/v1/leave/types",
        json={"name": name, "code": code, "max_days_per_year": max_days, "is_unpaid": is_unpaid},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _allocate_balance(client, hr_token, leave_type_id, year=2026, total_days=12):
    resp = client.post(
        "/api/v1/leave/balances/allocate",
        json={"leave_type_id": leave_type_id, "year": year, "total_days": total_days},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _apply_for_leave(client, employee_token, leave_type_id, from_date, to_date, reason="Personal"):
    return client.post(
        "/api/v1/leave/applications",
        headers=auth_headers(employee_token),
        data={"leave_type_id": str(leave_type_id), "from_date": from_date, "to_date": to_date, "reason": reason},
    )


def test_two_stage_leave_approval_happy_path(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    manager = _create_employee(client, hr_token, "manager@example.com", full_name="Manny Manager")
    _create_employee(
        client, hr_token, "alice@example.com", full_name="Alice Example", manager_id=manager["id"]
    )

    leave_type = _create_leave_type(client, hr_token)
    _allocate_balance(client, hr_token, leave_type["id"])

    manager_token = login(client, "manager@example.com", "InitialPass123!")
    employee_token = login(client, "alice@example.com", "InitialPass123!")

    resp = _apply_for_leave(client, employee_token, leave_type["id"], "2026-03-02", "2026-03-04", "Family trip")
    assert resp.status_code == 201, resp.text
    application = resp.json()
    assert application["status"] == "pending_manager"
    assert application["days"] == 3

    resp = client.post(
        f"/api/v1/leave/applications/{application['id']}/manager-action",
        json={"action": "approve", "comments": "OK by me"},
        headers=auth_headers(manager_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending_hr"

    resp = client.post(
        f"/api/v1/leave/applications/{application['id']}/hr-action",
        json={"action": "approve"},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"

    resp = client.get("/api/v1/leave/balances/me", headers=auth_headers(employee_token))
    balance = next(b for b in resp.json() if b["leave_type_id"] == leave_type["id"])
    assert balance["used"] == 3
    assert balance["remaining"] == 9

    resp = client.get(f"/api/v1/leave/applications/{application['id']}", headers=auth_headers(hr_token))
    history_actions = [h["action"] for h in resp.json()["history"]]
    assert history_actions == ["submitted", "manager_approved", "hr_approved"]


def test_leave_skips_to_hr_when_no_manager_assigned(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, "bob@example.com")
    leave_type = _create_leave_type(client, hr_token)
    _allocate_balance(client, hr_token, leave_type["id"])
    employee_token = login(client, "bob@example.com", "InitialPass123!")

    resp = _apply_for_leave(client, employee_token, leave_type["id"], "2026-03-02", "2026-03-02")
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "pending_hr"


def test_leave_application_rejected_when_balance_insufficient(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, "carol@example.com")
    leave_type = _create_leave_type(client, hr_token, max_days=2)
    _allocate_balance(client, hr_token, leave_type["id"], total_days=2)
    employee_token = login(client, "carol@example.com", "InitialPass123!")

    resp = _apply_for_leave(client, employee_token, leave_type["id"], "2026-03-02", "2026-03-06")
    assert resp.status_code == 400


def test_unpaid_leave_type_bypasses_balance_check(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, "dave@example.com")
    leave_type = _create_leave_type(client, hr_token, name="Loss of Pay", code="LOP", is_unpaid=True)
    employee_token = login(client, "dave@example.com", "InitialPass123!")

    resp = _apply_for_leave(client, employee_token, leave_type["id"], "2026-03-02", "2026-03-10")
    assert resp.status_code == 201, resp.text


def test_manager_cannot_act_on_non_reports_application(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    manager1 = _create_employee(client, hr_token, "manager1@example.com", full_name="Manager One")
    _create_employee(client, hr_token, "manager2@example.com", full_name="Manager Two")
    _create_employee(client, hr_token, "erin@example.com", manager_id=manager1["id"])

    leave_type = _create_leave_type(client, hr_token)
    _allocate_balance(client, hr_token, leave_type["id"])

    manager2_token = login(client, "manager2@example.com", "InitialPass123!")
    employee_token = login(client, "erin@example.com", "InitialPass123!")

    resp = _apply_for_leave(client, employee_token, leave_type["id"], "2026-03-02", "2026-03-02")
    application_id = resp.json()["id"]

    resp = client.post(
        f"/api/v1/leave/applications/{application_id}/manager-action",
        json={"action": "approve"},
        headers=auth_headers(manager2_token),
    )
    assert resp.status_code == 403


def test_cancel_while_pending_and_not_after_approval(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, "frank@example.com")
    leave_type = _create_leave_type(client, hr_token)
    _allocate_balance(client, hr_token, leave_type["id"])
    employee_token = login(client, "frank@example.com", "InitialPass123!")

    resp = _apply_for_leave(client, employee_token, leave_type["id"], "2026-03-02", "2026-03-02")
    application_id = resp.json()["id"]

    resp = client.post(
        f"/api/v1/leave/applications/{application_id}/cancel", headers=auth_headers(employee_token)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    resp = _apply_for_leave(client, employee_token, leave_type["id"], "2026-03-10", "2026-03-10")
    application_id2 = resp.json()["id"]
    client.post(
        f"/api/v1/leave/applications/{application_id2}/hr-action",
        json={"action": "approve"},
        headers=auth_headers(hr_token),
    )

    resp = client.post(
        f"/api/v1/leave/applications/{application_id2}/cancel", headers=auth_headers(employee_token)
    )
    assert resp.status_code == 400


def test_balance_allocation_is_idempotent(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, "grace@example.com")
    leave_type = _create_leave_type(client, hr_token)

    first = _allocate_balance(client, hr_token, leave_type["id"])
    assert first["created"] == 1

    second = _allocate_balance(client, hr_token, leave_type["id"])
    assert second["created"] == 0
    assert second["skipped"] == 1


def test_hr_can_override_at_manager_stage(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    manager = _create_employee(client, hr_token, "manager3@example.com", full_name="Manager Three")
    _create_employee(client, hr_token, "heidi@example.com", manager_id=manager["id"])

    leave_type = _create_leave_type(client, hr_token)
    _allocate_balance(client, hr_token, leave_type["id"])
    employee_token = login(client, "heidi@example.com", "InitialPass123!")

    resp = _apply_for_leave(client, employee_token, leave_type["id"], "2026-03-02", "2026-03-02")
    application_id = resp.json()["id"]

    resp = client.post(
        f"/api/v1/leave/applications/{application_id}/manager-action",
        json={"action": "approve"},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending_hr"
