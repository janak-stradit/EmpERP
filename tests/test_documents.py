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


def _create_category(client, hr_token, name="ID Proof"):
    resp = client.post(
        "/api/v1/documents/categories", json={"name": name}, headers=auth_headers(hr_token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _setup_hr_and_employee(client, db_session):
    company = create_company(db_session)
    create_user(db_session, company, "hr@example.com", "Password123!", role=UserRole.HR)
    hr_token = login(client, "hr@example.com", "Password123!")
    _create_employee(client, hr_token)
    employee_token = login(client, "alice@example.com", "InitialPass123!")
    category_id = _create_category(client, hr_token)
    return hr_token, employee_token, category_id


def test_employee_uploads_document_successfully(client, db_session):
    hr_token, employee_token, category_id = _setup_hr_and_employee(client, db_session)

    resp = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers(employee_token),
        data={"category_id": str(category_id)},
        files={"file": ("id_card.pdf", b"%PDF-1.4 fake content", "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    document = resp.json()
    assert document["status"] == "pending"
    assert document["file_name"] == "id_card.pdf"

    resp = client.get("/api/v1/documents", headers=auth_headers(employee_token))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_upload_rejects_disallowed_extension(client, db_session):
    hr_token, employee_token, category_id = _setup_hr_and_employee(client, db_session)

    resp = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers(employee_token),
        data={"category_id": str(category_id)},
        files={"file": ("malware.exe", b"binary content", "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_upload_rejects_oversized_file(client, db_session):
    hr_token, employee_token, category_id = _setup_hr_and_employee(client, db_session)

    oversized_content = b"a" * (10 * 1024 * 1024 + 1)
    resp = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers(employee_token),
        data={"category_id": str(category_id)},
        files={"file": ("big.pdf", oversized_content, "application/pdf")},
    )
    assert resp.status_code == 400


def test_hr_can_verify_document(client, db_session):
    hr_token, employee_token, category_id = _setup_hr_and_employee(client, db_session)

    resp = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers(employee_token),
        data={"category_id": str(category_id)},
        files={"file": ("id_card.pdf", b"%PDF-1.4 fake content", "application/pdf")},
    )
    document_id = resp.json()["id"]

    resp = client.post(
        f"/api/v1/documents/{document_id}/verify",
        json={"status": "approved"},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    assert resp.json()["verified_by"] is not None


def test_other_employee_cannot_view_or_download_document(client, db_session):
    hr_token, employee_token, category_id = _setup_hr_and_employee(client, db_session)
    _create_employee(client, hr_token, email="mallory@example.com")
    mallory_token = login(client, "mallory@example.com", "InitialPass123!")

    resp = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers(employee_token),
        data={"category_id": str(category_id)},
        files={"file": ("id_card.pdf", b"%PDF-1.4 fake content", "application/pdf")},
    )
    document_id = resp.json()["id"]

    resp = client.get(f"/api/v1/documents/{document_id}/download", headers=auth_headers(mallory_token))
    assert resp.status_code == 403

    resp = client.get("/api/v1/documents", headers=auth_headers(mallory_token))
    assert resp.status_code == 200
    assert resp.json() == []


def test_hr_sees_all_company_documents_by_default(client, db_session):
    hr_token, employee_token, category_id = _setup_hr_and_employee(client, db_session)
    _create_employee(client, hr_token, email="mallory@example.com")
    mallory_token = login(client, "mallory@example.com", "InitialPass123!")

    for token in (employee_token, mallory_token):
        resp = client.post(
            "/api/v1/documents/upload",
            headers=auth_headers(token),
            data={"category_id": str(category_id)},
            files={"file": ("id_card.pdf", b"%PDF-1.4 fake content", "application/pdf")},
        )
        assert resp.status_code == 201, resp.text

    resp = client.get("/api/v1/documents", headers=auth_headers(hr_token))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_hr_can_filter_documents_by_employee_and_status(client, db_session):
    hr_token, employee_token, category_id = _setup_hr_and_employee(client, db_session)
    employee = client.get("/api/v1/employees/me", headers=auth_headers(employee_token)).json()

    resp = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers(employee_token),
        data={"category_id": str(category_id)},
        files={"file": ("id_card.pdf", b"%PDF-1.4 fake content", "application/pdf")},
    )
    document_id = resp.json()["id"]

    resp = client.get(
        f"/api/v1/documents?employee_id={employee['id']}", headers=auth_headers(hr_token)
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = client.get("/api/v1/documents?status_filter=approved", headers=auth_headers(hr_token))
    assert resp.status_code == 200
    assert resp.json() == []

    client.post(
        f"/api/v1/documents/{document_id}/verify",
        json={"status": "approved"},
        headers=auth_headers(hr_token),
    )

    resp = client.get("/api/v1/documents?status_filter=approved", headers=auth_headers(hr_token))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_reject_document_stores_review_notes_visible_to_employee(client, db_session):
    hr_token, employee_token, category_id = _setup_hr_and_employee(client, db_session)

    resp = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers(employee_token),
        data={"category_id": str(category_id)},
        files={"file": ("id_card.pdf", b"%PDF-1.4 fake content", "application/pdf")},
    )
    document_id = resp.json()["id"]

    resp = client.post(
        f"/api/v1/documents/{document_id}/verify",
        json={"status": "rejected", "notes": "Photo is blurry, please re-upload"},
        headers=auth_headers(hr_token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert resp.json()["review_notes"] == "Photo is blurry, please re-upload"

    resp = client.get("/api/v1/documents", headers=auth_headers(employee_token))
    assert resp.json()[0]["review_notes"] == "Photo is blurry, please re-upload"


def test_hr_can_download_employee_documents_as_zip(client, db_session):
    import zipfile
    from io import BytesIO

    hr_token, employee_token, category_id = _setup_hr_and_employee(client, db_session)
    employee = client.get("/api/v1/employees/me", headers=auth_headers(employee_token)).json()

    for name in ("id_card.pdf", "address_proof.pdf"):
        resp = client.post(
            "/api/v1/documents/upload",
            headers=auth_headers(employee_token),
            data={"category_id": str(category_id)},
            files={"file": (name, b"%PDF-1.4 fake content", "application/pdf")},
        )
        assert resp.status_code == 201, resp.text

    resp = client.get(f"/api/v1/documents/employee/{employee['id']}/zip", headers=auth_headers(hr_token))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert _parse_zip_filename(resp.headers["content-disposition"]) == "EMP0001_Alice_Example.zip"

    zip_file = zipfile.ZipFile(BytesIO(resp.content))
    assert len(zip_file.namelist()) == 2


def test_zip_download_rejects_employee_with_no_documents(client, db_session):
    hr_token, employee_token, category_id = _setup_hr_and_employee(client, db_session)
    employee = client.get("/api/v1/employees/me", headers=auth_headers(employee_token)).json()

    resp = client.get(f"/api/v1/documents/employee/{employee['id']}/zip", headers=auth_headers(hr_token))
    assert resp.status_code == 404


def test_employee_cannot_download_zip(client, db_session):
    hr_token, employee_token, category_id = _setup_hr_and_employee(client, db_session)
    employee = client.get("/api/v1/employees/me", headers=auth_headers(employee_token)).json()

    resp = client.get(f"/api/v1/documents/employee/{employee['id']}/zip", headers=auth_headers(employee_token))
    assert resp.status_code == 403


def _parse_zip_filename(content_disposition: str) -> str:
    return content_disposition.split("filename=")[1].strip('"')
