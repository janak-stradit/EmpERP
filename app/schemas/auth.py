from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LoginResponse(BaseModel):
    requires_2fa: bool
    pre_2fa_token: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"


class TwoFAVerifyRequest(BaseModel):
    pre_2fa_token: str
    code: str = Field(min_length=6, max_length=6)


class TwoFAEnableRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class TwoFASetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class MessageResponse(BaseModel):
    message: str


class CurrentUserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_2fa_enabled: bool
