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


def _create_cycle(client, hr_token, name="2026 Annual Review"):
    resp = client.post(
        "/api/v1/kra/cycles",
        json={"name": name, "start_date": "2026-01-01", "end_date": "2026-12-31"},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_template(client, hr_token, items):
    resp = client.post(
        "/api/v1/kra/templates",
        json={"name": "Standard Template", "description": "Default"},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 201, resp.text
    template = resp.json()
    for item in items:
        resp = client.post(
            f"/api/v1/kra/templates/{template['id']}/items",
            json=item,
            headers=auth_headers(hr_token),
        )
        assert resp.status_code == 201, resp.text
        template = resp.json()
    return template


def test_weightage_must_sum_to_100_on_assignment(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    employee = _create_employee(client, hr_token, "alice@example.com")
    cycle = _create_cycle(client, hr_token)
    template = _create_template(
        client, hr_token,
        [
            {"title": "Delivery", "default_weightage": 40},
            {"title": "Quality", "default_weightage": 40},
        ],
    )

    resp = client.post(
        "/api/v1/kra/assign",
        json={"employee_id": employee["id"], "cycle_id": cycle["id"], "template_id": template["id"]},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 400
    assert "100" in resp.json()["detail"]


def test_full_kra_lifecycle_happy_path(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    manager = _create_employee(client, hr_token, "manager@example.com", full_name="Manny Manager")
    employee = _create_employee(
        client, hr_token, "alice@example.com", full_name="Alice Example", manager_id=manager["id"]
    )

    cycle = _create_cycle(client, hr_token)
    template = _create_template(
        client, hr_token,
        [
            {"title": "Delivery", "default_weightage": 60},
            {"title": "Quality", "default_weightage": 40},
        ],
    )

    resp = client.post(
        "/api/v1/kra/assign",
        json={"employee_id": employee["id"], "cycle_id": cycle["id"], "template_id": template["id"]},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 201, resp.text
    employee_kra = resp.json()
    assert employee_kra["status"] == "draft"
    items = employee_kra["items"]
    assert {i["weightage"] for i in items} == {60, 40}

    employee_token = login(client, "alice@example.com", "InitialPass123!")
    manager_token = login(client, "manager@example.com", "InitialPass123!")

    resp = client.put(
        f"/api/v1/kra/{employee_kra['id']}/self-rating",
        json={"items": [{"item_id": items[0]["id"], "rating": 4, "comment": "Good"}, {"item_id": items[1]["id"], "rating": 3, "comment": "OK"}]},
        headers=auth_headers(employee_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(f"/api/v1/kra/{employee_kra['id']}/submit", headers=auth_headers(employee_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "submitted"

    resp = client.put(
        f"/api/v1/kra/{employee_kra['id']}/manager-rating",
        json={"items": [{"item_id": items[0]["id"], "rating": 5, "comment": "Great"}, {"item_id": items[1]["id"], "rating": 4, "comment": "Solid"}]},
        headers=auth_headers(manager_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(f"/api/v1/kra/{employee_kra['id']}/complete-review", headers=auth_headers(manager_token))
    assert resp.status_code == 200, resp.text
    reviewed = resp.json()
    assert reviewed["status"] == "reviewed"
    item_by_title = {i["title"]: i for i in reviewed["items"]}
    assert item_by_title["Delivery"]["score"] == 3.0  # 5 * 60/100
    assert item_by_title["Quality"]["score"] == 1.6  # 4 * 40/100

    resp = client.post(f"/api/v1/kra/{employee_kra['id']}/approve", headers=auth_headers(hr_token))
    assert resp.status_code == 200, resp.text
    approved = resp.json()
    assert approved["status"] == "approved"
    assert round(approved["overall_score"], 2) == 4.6


def test_manager_cannot_rate_non_reports_kra(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    manager1 = _create_employee(client, hr_token, "manager1@example.com", full_name="Manager One")
    _create_employee(client, hr_token, "manager2@example.com", full_name="Manager Two")
    employee = _create_employee(client, hr_token, "erin@example.com", manager_id=manager1["id"])

    cycle = _create_cycle(client, hr_token)
    template = _create_template(client, hr_token, [{"title": "Delivery", "default_weightage": 100}])

    resp = client.post(
        "/api/v1/kra/assign",
        json={"employee_id": employee["id"], "cycle_id": cycle["id"], "template_id": template["id"]},
        headers=auth_headers(hr_token),
    )
    employee_kra = resp.json()

    employee_token = login(client, "erin@example.com", "InitialPass123!")
    client.put(
        f"/api/v1/kra/{employee_kra['id']}/self-rating",
        json={"items": [{"item_id": employee_kra["items"][0]["id"], "rating": 4}]},
        headers=auth_headers(employee_token),
    )
    client.post(f"/api/v1/kra/{employee_kra['id']}/submit", headers=auth_headers(employee_token))

    manager2_token = login(client, "manager2@example.com", "InitialPass123!")
    resp = client.put(
        f"/api/v1/kra/{employee_kra['id']}/manager-rating",
        json={"items": [{"item_id": employee_kra["items"][0]["id"], "rating": 5}]},
        headers=auth_headers(manager2_token),
    )
    assert resp.status_code == 403


def test_cannot_assign_duplicate_kra_for_same_cycle(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    employee = _create_employee(client, hr_token, "alice@example.com")
    cycle = _create_cycle(client, hr_token)
    template = _create_template(client, hr_token, [{"title": "Delivery", "default_weightage": 100}])

    resp = client.post(
        "/api/v1/kra/assign",
        json={"employee_id": employee["id"], "cycle_id": cycle["id"], "template_id": template["id"]},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 201

    resp = client.post(
        "/api/v1/kra/assign",
        json={"employee_id": employee["id"], "cycle_id": cycle["id"], "template_id": template["id"]},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 400
