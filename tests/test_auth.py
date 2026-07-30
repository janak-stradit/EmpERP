import pyotp

from app.core.security import hash_password
from app.models import Company, User
from app.models.user import UserRole


def _create_user(db_session, email, password, role=UserRole.EMPLOYEE):
    company = Company(name="Test Co")
    db_session.add(company)
    db_session.flush()
    user = User(
        company_id=company.id,
        email=email,
        password_hash=hash_password(password),
        full_name="Test User",
        role=role,
        is_active=True,
        is_2fa_enabled=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_login_success(client, db_session):
    _create_user(db_session, "alice@example.com", "Password123!")

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "Password123!"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["requires_2fa"] is False
    assert data["access_token"]
    assert data["refresh_token"]


def test_login_wrong_password_then_lockout(client, db_session):
    _create_user(db_session, "bob@example.com", "Password123!")

    for _ in range(5):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "bob@example.com", "password": "wrong-password"},
        )
        assert resp.status_code == 401

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": "Password123!"},
    )
    assert resp.status_code == 429


def test_2fa_setup_enable_and_login_flow(client, db_session):
    _create_user(db_session, "carol@example.com", "Password123!")

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "carol@example.com", "password": "Password123!"},
    )
    access_token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    setup_resp = client.post("/api/v1/auth/2fa/setup", headers=headers)
    assert setup_resp.status_code == 200
    secret = setup_resp.json()["secret"]

    enable_resp = client.post(
        "/api/v1/auth/2fa/enable",
        json={"code": pyotp.TOTP(secret).now()},
        headers=headers,
    )
    assert enable_resp.status_code == 200

    second_login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "carol@example.com", "password": "Password123!"},
    )
    assert second_login_resp.status_code == 200
    second_login_data = second_login_resp.json()
    assert second_login_data["requires_2fa"] is True
    pre_2fa_token = second_login_data["pre_2fa_token"]

    verify_resp = client.post(
        "/api/v1/auth/2fa/verify",
        json={"pre_2fa_token": pre_2fa_token, "code": pyotp.TOTP(secret).now()},
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["access_token"]


def test_me_requires_auth(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
