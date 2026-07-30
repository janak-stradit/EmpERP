from app.models.user import UserRole
from tests.helpers import auth_headers, create_company, create_user, login


def test_hr_can_create_and_list_departments(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    token = login(client, "hr@example.com", "Password123!")

    resp = client.post("/api/v1/departments", json={"name": "Engineering"}, headers=auth_headers(token))
    assert resp.status_code == 201
    dept_id = resp.json()["id"]

    resp = client.get("/api/v1/departments", headers=auth_headers(token))
    assert resp.status_code == 200
    assert any(d["id"] == dept_id for d in resp.json())


def test_employee_cannot_create_department(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "emp@example.com", "Password123!", role=UserRole.EMPLOYEE)
    token = login(client, "emp@example.com", "Password123!")

    resp = client.post("/api/v1/departments", json={"name": "Sales"}, headers=auth_headers(token))
    assert resp.status_code == 403


def test_soft_deleted_department_not_listed(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "admin@example.com", "Password123!", role=UserRole.ADMIN)
    token = login(client, "admin@example.com", "Password123!")

    resp = client.post("/api/v1/departments", json={"name": "Temp"}, headers=auth_headers(token))
    dept_id = resp.json()["id"]

    resp = client.delete(f"/api/v1/departments/{dept_id}", headers=auth_headers(token))
    assert resp.status_code == 204

    resp = client.get("/api/v1/departments", headers=auth_headers(token))
    assert all(d["id"] != dept_id for d in resp.json())

    resp = client.get(f"/api/v1/departments/{dept_id}", headers=auth_headers(token))
    assert resp.status_code == 404
