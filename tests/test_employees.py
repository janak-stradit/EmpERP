from app.models.user import UserRole
from tests.helpers import auth_headers, create_company, create_user, login


def _create_employee(client, hr_token, email="alice@example.com", bank_account_number="123456789"):
    resp = client.post(
        "/api/v1/employees",
        json={
            "email": email,
            "full_name": "Alice Example",
            "initial_password": "InitialPass123!",
            "role": "employee",
            "joining_date": "2026-01-01",
            "bank_account_number": bank_account_number,
        },
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_hr_creates_employee_with_encrypted_bank_details(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")

    employee = _create_employee(client, hr_token)
    assert employee["employee_code"] == "EMP0001"
    assert employee["bank_account_number"] == "123456789"

    from app.models.employee import Employee

    row = db_session.query(Employee).filter(Employee.id == employee["id"]).one()
    assert row.bank_account_number_encrypted != "123456789"
    assert row.bank_account_number_encrypted is not None


def test_employee_can_view_and_update_own_profile(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, email="bob@example.com")

    employee_token = login(client, "bob@example.com", "InitialPass123!")

    resp = client.get("/api/v1/employees/me", headers=auth_headers(employee_token))
    assert resp.status_code == 200
    assert resp.json()["email"] == "bob@example.com"

    resp = client.put("/api/v1/employees/me", json={"phone": "9999999999"}, headers=auth_headers(employee_token))
    assert resp.status_code == 200
    assert resp.json()["phone"] == "9999999999"


def test_employee_can_self_update_dob_gender_and_bank_details(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, email="heidi@example.com", bank_account_number=None)

    employee_token = login(client, "heidi@example.com", "InitialPass123!")

    resp = client.put(
        "/api/v1/employees/me",
        json={
            "date_of_birth": "1995-05-20",
            "gender": "female",
            "bank_account_number": "555000111",
            "bank_ifsc": "ABCD0123456",
            "bank_name": "Test Bank",
        },
        headers=auth_headers(employee_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["date_of_birth"] == "1995-05-20"
    assert data["gender"] == "female"
    assert data["bank_account_number"] == "555000111"
    assert data["bank_ifsc"] == "ABCD0123456"

    from app.models.employee import Employee

    row = db_session.query(Employee).filter(Employee.id == data["id"]).one()
    assert row.bank_account_number_encrypted != "555000111"
    assert row.bank_account_number_encrypted is not None


def test_employee_cannot_list_all_employees(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, email="carol@example.com")

    employee_token = login(client, "carol@example.com", "InitialPass123!")
    resp = client.get("/api/v1/employees", headers=auth_headers(employee_token))
    assert resp.status_code == 403


def test_employee_cannot_view_another_employees_profile(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    employee1 = _create_employee(client, hr_token, email="dave@example.com")
    _create_employee(client, hr_token, email="erin@example.com")

    dave_token = login(client, "dave@example.com", "InitialPass123!")
    resp = client.get(f"/api/v1/employees/{employee1['id'] + 1}", headers=auth_headers(dave_token))
    assert resp.status_code == 403


def test_hr_can_disable_and_reenable_employee_account(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    employee = _create_employee(client, hr_token, email="frank@example.com")

    resp = client.put(
        f"/api/v1/employees/{employee['id']}/access",
        json={"is_active": False},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    resp = client.post(
        "/api/v1/auth/login", json={"email": "frank@example.com", "password": "InitialPass123!"}
    )
    assert resp.status_code == 401

    resp = client.put(
        f"/api/v1/employees/{employee['id']}/access",
        json={"is_active": True},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True

    resp = client.post(
        "/api/v1/auth/login", json={"email": "frank@example.com", "password": "InitialPass123!"}
    )
    assert resp.status_code == 200


def test_employee_cannot_toggle_own_or_others_access(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    employee = _create_employee(client, hr_token, email="grace@example.com")

    employee_token = login(client, "grace@example.com", "InitialPass123!")
    resp = client.put(
        f"/api/v1/employees/{employee['id']}/access",
        json={"is_active": False},
        headers=auth_headers(employee_token),
    )
    assert resp.status_code == 403


def test_hr_cannot_disable_own_account_via_employee_endpoint(client, db_session):
    company = create_company(db_session)
    hr_user = create_user(db_session, company, "hr2@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr2@example.com", "Password123!")

    from app.models.employee import Employee

    self_employee = Employee(
        user_id=hr_user.id,
        company_id=company.id,
        employee_code="EMP-HR",
        joining_date="2026-01-01",
    )
    db_session.add(self_employee)
    db_session.commit()
    db_session.refresh(self_employee)

    resp = client.put(
        f"/api/v1/employees/{self_employee.id}/access",
        json={"is_active": False},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 400


def test_self_update_rejects_invalid_ifsc(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, email="ivan@example.com", bank_account_number=None)
    employee_token = login(client, "ivan@example.com", "InitialPass123!")

    resp = client.put(
        "/api/v1/employees/me", json={"bank_ifsc": "not-a-code"}, headers=auth_headers(employee_token)
    )
    assert resp.status_code == 422


def test_self_update_rejects_invalid_account_number(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, email="judy@example.com", bank_account_number=None)
    employee_token = login(client, "judy@example.com", "InitialPass123!")

    resp = client.put(
        "/api/v1/employees/me", json={"bank_account_number": "12AB"}, headers=auth_headers(employee_token)
    )
    assert resp.status_code == 422


def test_self_update_rejects_invalid_phone_format(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, email="karl@example.com", bank_account_number=None)
    employee_token = login(client, "karl@example.com", "InitialPass123!")

    resp = client.put(
        "/api/v1/employees/me", json={"phone": "call-me-maybe"}, headers=auth_headers(employee_token)
    )
    assert resp.status_code == 422


def test_self_update_rejects_invalid_gender(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, email="liam@example.com", bank_account_number=None)
    employee_token = login(client, "liam@example.com", "InitialPass123!")

    resp = client.put(
        "/api/v1/employees/me", json={"gender": "robot"}, headers=auth_headers(employee_token)
    )
    assert resp.status_code == 422


def test_self_update_accepts_phone_with_country_code(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token, email="mia@example.com", bank_account_number=None)
    employee_token = login(client, "mia@example.com", "InitialPass123!")

    resp = client.put(
        "/api/v1/employees/me",
        json={"phone": "+91 9876543210", "emergency_contact_phone": "+1 4155552671"},
        headers=auth_headers(employee_token),
    )
    assert resp.status_code == 200
    assert resp.json()["phone"] == "+91 9876543210"
    assert resp.json()["emergency_contact_phone"] == "+1 4155552671"


def test_profile_photo_upload_view_and_replace(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    employee = _create_employee(client, hr_token, email="nora@example.com", bank_account_number=None)
    employee_token = login(client, "nora@example.com", "InitialPass123!")

    resp = client.get("/api/v1/employees/me", headers=auth_headers(employee_token))
    assert resp.json()["has_profile_photo"] is False

    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c4944415478da6360000002000155bfaa0d0000000049454e44ae426082"
    )
    resp = client.post(
        "/api/v1/employees/me/photo",
        headers=auth_headers(employee_token),
        files={"file": ("avatar.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["has_profile_photo"] is True

    resp = client.get(f"/api/v1/employees/{employee['id']}/photo", headers=auth_headers(employee_token))
    assert resp.status_code == 200
    assert resp.content == png_bytes

    resp = client.get(f"/api/v1/employees/{employee['id']}/photo", headers=auth_headers(hr_token))
    assert resp.status_code == 200


def test_profile_photo_rejects_non_image_and_unauthorized_viewer(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    employee = _create_employee(client, hr_token, email="oscar@example.com", bank_account_number=None)
    _create_employee(client, hr_token, email="peggy@example.com", bank_account_number=None)
    employee_token = login(client, "oscar@example.com", "InitialPass123!")
    peggy_token = login(client, "peggy@example.com", "InitialPass123!")

    resp = client.post(
        "/api/v1/employees/me/photo",
        headers=auth_headers(employee_token),
        files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert resp.status_code == 400

    resp = client.get(f"/api/v1/employees/{employee['id']}/photo", headers=auth_headers(peggy_token))
    assert resp.status_code == 403


def test_hr_can_promote_employee_to_hr_role(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    employee = _create_employee(client, hr_token, email="quinn@example.com", bank_account_number=None)

    quinn_token = login(client, "quinn@example.com", "InitialPass123!")
    resp = client.get("/api/v1/documents", headers=auth_headers(quinn_token))
    assert resp.status_code == 200
    assert resp.json() == []

    resp = client.put(
        f"/api/v1/employees/{employee['id']}", json={"role": "hr"}, headers=auth_headers(hr_token)
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "hr"

    quinn_token = login(client, "quinn@example.com", "InitialPass123!")
    resp = client.get("/api/v1/employees", headers=auth_headers(quinn_token))
    assert resp.status_code == 200


def test_update_employee_rejects_invalid_role(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    employee = _create_employee(client, hr_token, email="ray@example.com", bank_account_number=None)

    resp = client.put(
        f"/api/v1/employees/{employee['id']}",
        json={"role": "super_admin"},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 400


def test_hr_cannot_change_own_role_via_employee_endpoint(client, db_session):
    company = create_company(db_session)
    hr_user = create_user(db_session, company, "hr3@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr3@example.com", "Password123!")

    from app.models.employee import Employee

    self_employee = Employee(
        user_id=hr_user.id,
        company_id=company.id,
        employee_code="EMP-HR2",
        joining_date="2026-01-01",
    )
    db_session.add(self_employee)
    db_session.commit()
    db_session.refresh(self_employee)

    resp = client.put(
        f"/api/v1/employees/{self_employee.id}", json={"role": "employee"}, headers=auth_headers(hr_token)
    )
    assert resp.status_code == 400
