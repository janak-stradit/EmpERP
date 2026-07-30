from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_client_ip, get_current_user, get_db
from app.core.audit import log_audit
from app.core.config import get_settings
from app.core.security import (
    PRE_2FA_TOKEN_TYPE,
    create_access_token,
    create_pre_2fa_token,
    decode_token,
    decrypt_secret,
    encrypt_secret,
    generate_refresh_token,
    generate_totp_secret,
    get_totp_provisioning_uri,
    hash_refresh_token,
    verify_password,
    verify_totp_code,
)
from app.models.login_attempt import LoginAttempt
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import (
    CurrentUserResponse,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    MessageResponse,
    RefreshRequest,
    TokenResponse,
    TwoFAEnableRequest,
    TwoFASetupResponse,
    TwoFAVerifyRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _is_locked_out(db: Session, ip_address: str) -> bool:
    window_start = datetime.now(timezone.utc) - timedelta(minutes=settings.login_lockout_window_minutes)
    failed_count = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.ip_address == ip_address,
            LoginAttempt.success.is_(False),
            LoginAttempt.attempted_at >= window_start,
        )
    )
    return (failed_count or 0) >= settings.login_max_attempts


def _record_attempt(db: Session, *, user_id: int | None, ip_address: str, success: bool) -> None:
    db.add(LoginAttempt(user_id=user_id, ip_address=ip_address, success=success))
    db.commit()


def _issue_tokens(db: Session, user: User) -> TokenResponse:
    access_token = create_access_token(user.id, user.role.value)
    refresh_token = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    db.commit()
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    ip_address = get_client_ip(request)

    if _is_locked_out(db, ip_address):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
        )

    user = db.scalar(select(User).where(User.email == payload.email))

    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        _record_attempt(db, user_id=user.id if user else None, ip_address=ip_address, success=False)
        log_audit(db, user_id=user.id if user else None, action="login_failed", ip_address=ip_address)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    _record_attempt(db, user_id=user.id, ip_address=ip_address, success=True)
    log_audit(db, user_id=user.id, action="login_success", ip_address=ip_address)

    if user.is_2fa_enabled:
        return LoginResponse(requires_2fa=True, pre_2fa_token=create_pre_2fa_token(user.id))

    tokens = _issue_tokens(db, user)
    return LoginResponse(requires_2fa=False, **tokens.model_dump())


@router.post("/2fa/verify", response_model=TokenResponse)
def verify_2fa(payload: TwoFAVerifyRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    ip_address = get_client_ip(request)

    try:
        claims = decode_token(payload.pre_2fa_token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired 2FA session")

    if claims.get("type") != PRE_2FA_TOKEN_TYPE:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user = db.get(User, int(claims["sub"]))
    if user is None or not user.is_active or not user.totp_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid 2FA session")

    secret = decrypt_secret(user.totp_secret)
    if not verify_totp_code(secret, payload.code):
        _record_attempt(db, user_id=user.id, ip_address=ip_address, success=False)
        log_audit(db, user_id=user.id, action="2fa_verify_failed", ip_address=ip_address)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid 2FA code")

    log_audit(db, user_id=user.id, action="2fa_verify_success", ip_address=ip_address)
    return _issue_tokens(db, user)


@router.post("/2fa/setup", response_model=TwoFASetupResponse)
def setup_2fa(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> TwoFASetupResponse:
    secret = generate_totp_secret()
    current_user.totp_secret = encrypt_secret(secret)
    current_user.is_2fa_enabled = False
    db.commit()
    return TwoFASetupResponse(
        secret=secret,
        provisioning_uri=get_totp_provisioning_uri(secret, current_user.email),
    )


@router.post("/2fa/enable", response_model=MessageResponse)
def enable_2fa(
    payload: TwoFAEnableRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    if not current_user.totp_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA setup not initiated")

    secret = decrypt_secret(current_user.totp_secret)
    if not verify_totp_code(secret, payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid 2FA code")

    current_user.is_2fa_enabled = True
    db.commit()
    log_audit(db, user_id=current_user.id, action="2fa_enabled", ip_address=get_client_ip(request))
    return MessageResponse(message="2FA enabled successfully")


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    token_hash = hash_refresh_token(payload.refresh_token)
    record = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))

    if (
        record is None
        or record.revoked
        or record.expires_at < datetime.now(timezone.utc)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    record.revoked = True
    db.commit()
    return _issue_tokens(db, user)


@router.post("/logout", response_model=MessageResponse)
def logout(
    payload: LogoutRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    token_hash = hash_refresh_token(payload.refresh_token)
    record = db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash, RefreshToken.user_id == current_user.id
        )
    )
    if record is not None:
        record.revoked = True
        db.commit()

    log_audit(db, user_id=current_user.id, action="logout")
    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=CurrentUserResponse)
def me(current_user: User = Depends(get_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role.value,
        is_2fa_enabled=current_user.is_2fa_enabled,
    )
