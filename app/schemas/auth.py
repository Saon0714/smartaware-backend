"""Auth request and response models.

These become the frontend's TypeScript types via the OpenAPI schema, so field
names here are the field names the web app sees.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import ClientStatus, InviteStatus, UserRole

#: Applied to every password field. Length is the meaningful control; composition
#: rules mostly push people toward predictable substitutions.
PasswordField = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    must_change_password: bool
    mfa_enabled: bool
    last_login_at: datetime | None


class ClientSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_ref: str
    company_name: str | None
    status: ClientStatus
    onboarding_completed_at: datetime | None


class SessionOut(BaseModel):
    """Login and refresh response.

    The refresh token is absent by design — it is set as an httpOnly cookie and
    must never be readable by page JavaScript.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")
    user: UserOut


class MeOut(BaseModel):
    user: UserOut
    client: ClientSummary | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = PasswordField


class InviteCreateRequest(BaseModel):
    email: EmailStr
    role: UserRole = UserRole.CLIENT
    company_name: str | None = Field(default=None, max_length=255)


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    role: UserRole
    status: InviteStatus
    expires_at: datetime
    used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    prefill_company_name: str | None


class InviteCreatedOut(BaseModel):
    invite: InviteOut
    #: Populated only outside production, so the flow can be exercised locally
    #: without a mail server. Never returned from a live deployment.
    invite_url: str | None = None


class InviteCheckOut(BaseModel):
    """Public pre-flight for the sign-up page.

    Returns the invited address so the form can show who it is for, and nothing
    else about the account.
    """

    email: EmailStr
    company_name: str | None
    expires_at: datetime


class AcceptInviteRequest(BaseModel):
    password: str = PasswordField
    full_name: str | None = Field(default=None, max_length=255)


class MessageOut(BaseModel):
    message: str
