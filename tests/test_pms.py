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


def _create_cycle(client, hr_token, name="2026 Performance Cycle"):
    resp = client.post(
        "/api/v1/kra/cycles",
        json={"name": name, "start_date": "2026-01-01", "end_date": "2026-12-31"},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_competency(client, hr_token, name="Communication"):
    resp = client.post("/api/v1/pms/competencies", json={"name": name}, headers=auth_headers(hr_token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_self_and_manager_requests_auto_created_on_assignment(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    manager = _create_employee(client, hr_token, "manager@example.com", full_name="Manny Manager")
    employee = _create_employee(client, hr_token, "alice@example.com", manager_id=manager["id"])
    cycle = _create_cycle(client, hr_token)

    resp = client.post(
        f"/api/v1/pms/cycles/{cycle['id']}/assign-employee",
        json={"employee_id": employee["id"]},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 200, resp.text
    requests = resp.json()
    roles = sorted(r["reviewer_role"] for r in requests)
    assert roles == ["manager", "self"]

    # idempotent - calling again shouldn't duplicate
    resp2 = client.post(
        f"/api/v1/pms/cycles/{cycle['id']}/assign-employee",
        json={"employee_id": employee["id"]},
        headers=auth_headers(hr_token),
    )
    assert len(resp2.json()) == 2


def test_only_assigned_reviewer_can_submit_evaluation(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    employee = _create_employee(client, hr_token, "bob@example.com")
    outsider = _create_employee(client, hr_token, "eve@example.com", full_name="Eve Outsider")
    cycle = _create_cycle(client, hr_token)
    competency = _create_competency(client, hr_token)

    resp = client.post(
        f"/api/v1/pms/cycles/{cycle['id']}/assign-employee",
        json={"employee_id": employee["id"]},
        headers=auth_headers(hr_token),
    )
    self_request = next(r for r in resp.json() if r["reviewer_role"] == "self")

    outsider_token = login(client, "eve@example.com", "InitialPass123!")
    resp = client.post(
        "/api/v1/pms/evaluations",
        json={"review_request_id": self_request["id"], "items": [{"competency_id": competency["id"], "rating": 4}]},
        headers=auth_headers(outsider_token),
    )
    assert resp.status_code == 403

    employee_token = login(client, "bob@example.com", "InitialPass123!")
    resp = client.post(
        "/api/v1/pms/evaluations",
        json={"review_request_id": self_request["id"], "items": [{"competency_id": competency["id"], "rating": 4}]},
        headers=auth_headers(employee_token),
    )
    assert resp.status_code == 201, resp.text

    # Cannot submit twice for a completed request
    resp = client.post(
        "/api/v1/pms/evaluations",
        json={"review_request_id": self_request["id"], "items": [{"competency_id": competency["id"], "rating": 3}]},
        headers=auth_headers(employee_token),
    )
    assert resp.status_code == 400


def test_peer_reviewer_assignment_and_evaluation_visible_to_hr(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    employee = _create_employee(client, hr_token, "carol@example.com")
    peer = _create_employee(client, hr_token, "dave@example.com", full_name="Dave Peer")
    cycle = _create_cycle(client, hr_token)
    competency = _create_competency(client, hr_token)

    resp = client.post(
        f"/api/v1/pms/cycles/{cycle['id']}/assign-reviewer",
        json={"employee_id": employee["id"], "reviewer_user_id": peer["user_id"], "reviewer_role": "peer"},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 201, resp.text
    review_request = resp.json()
    assert review_request["reviewer_role"] == "peer"

    # duplicate assignment rejected
    resp = client.post(
        f"/api/v1/pms/cycles/{cycle['id']}/assign-reviewer",
        json={"employee_id": employee["id"], "reviewer_user_id": peer["user_id"], "reviewer_role": "peer"},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 400

    peer_token = login(client, "dave@example.com", "InitialPass123!")
    resp = client.get("/api/v1/pms/requests/me", headers=auth_headers(peer_token))
    assert len(resp.json()) == 1

    resp = client.post(
        "/api/v1/pms/evaluations",
        json={"review_request_id": review_request["id"], "items": [{"competency_id": competency["id"], "rating": 5, "comment": "Great teammate"}]},
        headers=auth_headers(peer_token),
    )
    assert resp.status_code == 201, resp.text

    resp = client.get(
        f"/api/v1/pms/employee/{employee['id']}", params={"cycle_id": cycle["id"]}, headers=auth_headers(hr_token)
    )
    assert resp.status_code == 200, resp.text
    evaluations = resp.json()
    assert len(evaluations) == 1
    assert evaluations[0]["evaluator_role"] == "peer"
    assert evaluations[0]["items"][0]["rating"] == 5


def test_rating_scale_bounds_enforced(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    employee = _create_employee(client, hr_token, "frank@example.com")
    cycle = _create_cycle(client, hr_token)
    competency = _create_competency(client, hr_token)
    resp = client.post(
        "/api/v1/pms/rating-scales", json={"name": "1-5 scale", "min_score": 1, "max_score": 5}, headers=auth_headers(hr_token)
    )
    assert resp.status_code == 201, resp.text

    resp = client.post(
        f"/api/v1/pms/cycles/{cycle['id']}/assign-employee",
        json={"employee_id": employee["id"]},
        headers=auth_headers(hr_token),
    )
    self_request = next(r for r in resp.json() if r["reviewer_role"] == "self")

    employee_token = login(client, "frank@example.com", "InitialPass123!")
    resp = client.post(
        "/api/v1/pms/evaluations",
        json={"review_request_id": self_request["id"], "items": [{"competency_id": competency["id"], "rating": 9}]},
        headers=auth_headers(employee_token),
    )
    assert resp.status_code == 400


def test_normalization_buckets_manager_average_only(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    manager = _create_employee(client, hr_token, "manager2@example.com", full_name="Manager Two")
    employee = _create_employee(client, hr_token, "grace@example.com", manager_id=manager["id"])
    cycle = _create_cycle(client, hr_token)
    competency = _create_competency(client, hr_token)

    resp = client.post(
        f"/api/v1/pms/cycles/{cycle['id']}/assign-employee",
        json={"employee_id": employee["id"]},
        headers=auth_headers(hr_token),
    )
    requests_by_role = {r["reviewer_role"]: r for r in resp.json()}

    employee_token = login(client, "grace@example.com", "InitialPass123!")
    client.post(
        "/api/v1/pms/evaluations",
        json={"review_request_id": requests_by_role["self"]["id"], "items": [{"competency_id": competency["id"], "rating": 3}]},
        headers=auth_headers(employee_token),
    )

    manager_token = login(client, "manager2@example.com", "InitialPass123!")
    client.post(
        "/api/v1/pms/evaluations",
        json={"review_request_id": requests_by_role["manager"]["id"], "items": [{"competency_id": competency["id"], "rating": 5}]},
        headers=auth_headers(manager_token),
    )

    resp = client.get(f"/api/v1/pms/cycles/{cycle['id']}/normalization", headers=auth_headers(hr_token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["employees"]) == 1
    assert data["employees"][0]["manager_average"] == 5.0
    total_bucketed = sum(b["count"] for b in data["buckets"])
    assert total_bucketed == 1


def test_promotion_recommendation_created_by_manager_and_toggled_by_hr(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    manager = _create_employee(client, hr_token, "manager3@example.com", full_name="Manager Three")
    employee = _create_employee(client, hr_token, "heidi@example.com", manager_id=manager["id"])
    cycle = _create_cycle(client, hr_token)
    manager_token = login(client, "manager3@example.com", "InitialPass123!")

    resp = client.post(
        "/api/v1/pms/promotions",
        json={"employee_id": employee["id"], "cycle_id": cycle["id"], "reason": "Outstanding performance"},
        headers=auth_headers(manager_token),
    )
    assert resp.status_code == 201, resp.text
    promo = resp.json()
    assert promo["status"] == "pending"

    resp = client.put(
        f"/api/v1/pms/promotions/{promo['id']}", json={"status": "approved"}, headers=auth_headers(hr_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


def test_non_manager_non_hr_cannot_recommend_promotion(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    employee = _create_employee(client, hr_token, "ivan@example.com")
    outsider = _create_employee(client, hr_token, "judy@example.com", full_name="Judy Outsider")
    cycle = _create_cycle(client, hr_token)
    outsider_token = login(client, "judy@example.com", "InitialPass123!")

    resp = client.post(
        "/api/v1/pms/promotions",
        json={"employee_id": employee["id"], "cycle_id": cycle["id"], "reason": "N/A"},
        headers=auth_headers(outsider_token),
    )
    assert resp.status_code == 403
