from collections.abc import Callable, Generator

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import ACCESS_TOKEN_TYPE, decode_token
from app.db.session import SessionLocal
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)

HR_WRITE_ROLES = ("super_admin", "admin", "hr")
ADMIN_ROLES = ("super_admin", "admin")

# Endpoints a user must still be able to reach while must_change_password is set,
# so they can actually clear it (and check their own status / sign out).
PASSWORD_CHANGE_EXEMPT_PATHS = {
    "/api/v1/auth/change-password",
    "/api/v1/auth/me",
    "/api/v1/auth/logout",
    "/api/v1/auth/refresh",
}


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    if user.must_change_password and request.url.path not in PASSWORD_CHANGE_EXEMPT_PATHS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="password_change_required")

    return user


def require_role(*roles: str) -> Callable[[User], User]:
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.value not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return dependency
