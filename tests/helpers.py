from app.core.security import hash_password
from app.models import Company, User
from app.models.user import UserRole


def create_company(db_session, name="Test Co") -> Company:
    company = Company(name=name)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    return company


def create_user(db_session, company, email, password, role=UserRole.EMPLOYEE, full_name="Test User") -> User:
    user = User(
        company_id=company.id,
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=role,
        is_active=True,
        must_change_password=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def login(client, email, password) -> str:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
