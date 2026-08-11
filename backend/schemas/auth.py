import uuid

from pydantic import BaseModel, EmailStr, ConfigDict, Field

from models.user import UserRole


class UserRegister(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: EmailStr
    role: UserRole
    totp_enabled: bool
    is_active: bool


class UserRoleUpdate(BaseModel):
    role: UserRole


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginTotpSetupRequired(BaseModel):
    status: str = "totp_setup_required"
    pre_auth_token: str
    provisioning_uri: str
    qr_code_base64: str


class LoginTotpRequired(BaseModel):
    status: str = "totp_required"
    pre_auth_token: str


class TokenPair(BaseModel):
    status: str = "ok"
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TotpVerifyRequest(BaseModel):
    pre_auth_token: str
    code: str = Field(min_length=6, max_length=6)


class RefreshRequest(BaseModel):
    refresh_token: str


class TotpResetResponse(BaseModel):
    detail: str
