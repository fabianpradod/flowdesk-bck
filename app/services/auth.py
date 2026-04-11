from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone

from app.models.users import User
from app.models.roles import Role
from app.models.companies import Company
from app.schemas.users import UserCreate
from app.utils.exceptions import AppError
from app.schemas.companies import CompanyCreate
from app.core.security import decode_access_token
from app.core.security import hash_password, verify_password, create_access_token

_reset_attempts: dict[str, list] = {}

# ─── email placeholder ────────────────────────────────────────────
def _send_password_set_email(email: str, token: str):
    # TODO: replace with AWS SES when ready
    print(f"[EMAIL] Send to {email} → /auth/set-password?token={token}")

def _send_password_reset_email(email: str, token: str):
    # TODO: replace with AWS SES when ready
    print(f"[EMAIL] Send to {email} → /auth/reset-password?token={token}")

# ─── schema creation placeholder ──────────────────────────────────
def _create_tenant_schema(schema_name: str, engine):
    # TODO: expand this to also create tenant tables when ready
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
        conn.commit()

def _check_rate_limit(email: str):
    now = datetime.now(timezone.utc)
    attempts = _reset_attempts.get(email, [])
    # keep only attempts from the last 24h
    attempts = [a for a in attempts if now - a < timedelta(hours=24)]
    if len(attempts) >= 3:
        raise AppError(status_code=429, message="Too many reset attempts, try again later")
    attempts.append(now)
    _reset_attempts[email] = attempts

# ─── company registration ──────────────────────────────────────────
def register_company(data: CompanyCreate, db: Session, engine) -> Company:
    existing = db.query(Company).filter(Company.schema_name == data.schema_name).first()
    if existing:
        raise AppError(status_code=400, message="schema_name already taken")

    company = Company(
        name=data.name,
        schema_name=data.schema_name,
    )
    db.add(company)
    db.flush()  # gets us company.id without committing yet

    admin_role = db.query(Role).filter(Role.name == "admin").first()
    if not admin_role:
        raise AppError(status_code=500, message="Admin role not found")

    admin = User(
        username=data.admin_username,
        email=data.admin_email,
        password="",
        role_id=admin_role.id,    # ← integer id, not string
        company_id=company.id,
    )
    db.add(admin)
    db.commit()
    db.refresh(company)

    _create_tenant_schema(data.schema_name, engine)

    token = create_access_token(
        {"sub": str(admin.id), "purpose": "set_password"},
        expires_delta=timedelta(hours=48)
    )
    _send_password_set_email(data.admin_email, token)

    return company

# ─── login ────────────────────────────────────────────────────────
def login(email: str, password: str, db: Session) -> dict:
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password):
        raise AppError(status_code=401, message="Invalid credentials")

    if not user.password:
        raise AppError(status_code=403, message="Password not set yet, check your email")

    company = db.query(Company).filter(Company.id == user.company_id).first() if user.company_id else None

    token = create_access_token({
        "sub": str(user.id),
        "role": user.role.name,
        "company_id": str(user.company_id) if user.company_id else None,
        "schema_name": company.schema_name if company else None,
    })

    return {"access_token": token, "token_type": "bearer"}

def create_employee(data: UserCreate, admin: User, db: Session) -> User:
    if not admin.company_id:  # superadmin
        if not data.company_id:
            raise AppError(status_code=400, message="company_id is required when creating employees as superadmin")
        company = db.query(Company).filter(Company.id == data.company_id).first()
        if not company:
            raise AppError(status_code=404, message="Company not found")
        target_company_id = data.company_id
    else:
        target_company_id = admin.company_id  # taken from token as before

    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise AppError(status_code=400, message="Email already registered")

    employee = User(
        username=data.username,
        email=data.email,
        password="",  # not set yet
        role_id=data.role_id,
        company_id=target_company_id,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)

    token = create_access_token(
        {"sub": str(employee.id), "purpose": "set_password"},
        expires_delta=timedelta(hours=48)
    )
    _send_password_set_email(data.email, token)

    return employee

# ─── set password ─────────────────────────────────────────────────
def set_password(token: str, new_password: str, db: Session) -> dict:

    payload = decode_access_token(token)

    if not payload or payload.get("purpose") != "set_password":
        raise AppError(status_code=400, message="Invalid or expired token")

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise AppError(status_code=404, message="User not found")

    user.password = hash_password(new_password)
    user.is_active = True
    db.commit()

    return {"message": "Password set successfully"}

def reset_password(token: str, new_password: str, db: Session) -> dict:
    payload = decode_access_token(token)

    if not payload or payload.get("purpose") != "reset_password":
        raise AppError(status_code=400, message="Invalid or expired token")

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise AppError(status_code=404, message="User not found")

    if not user.is_active:
        raise AppError(status_code=403, message="Account is not active")

    user.password = hash_password(new_password)
    db.commit()

    return {"message": "Password reset successfully"}

def resend_invitation(email: str, db: Session):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise AppError(status_code=404, message="User not found")
    if user.is_active:
        raise AppError(status_code=400, message="User is already active")

    token = create_access_token(
        {"sub": str(user.id), "purpose": "set_password"},
        expires_delta=timedelta(hours=48)
    )
    _send_password_set_email(email, token)

    return {"message": "Invitation resent successfully"}

def forgot_password(email: str, db: Session):
    _check_rate_limit(email)
    user = db.query(User).filter(User.email == email).first()
    if user and user.is_active and user.password:
        token = create_access_token(
            {"sub": str(user.id), "purpose": "reset_password"},
            expires_delta=timedelta(hours=48)
        )
        _send_password_reset_email(email, token)
    # always return the same response
    return {"message": "If that email exists, a reset link was sent"}
