from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.users import User
from app.models.companies import Company
from app.schemas.users import UserCreate
from app.utils.exceptions import AppError
from app.schemas.companies import CompanyCreate
from app.core.security import decode_access_token
from app.core.security import hash_password, verify_password, create_access_token

# ─── email placeholder ────────────────────────────────────────────
def _send_password_set_email(email: str, token: str):
    # TODO: replace with AWS SES when ready
    print(f"[EMAIL] Send to {email} → /auth/set-password?token={token}")

# ─── schema creation placeholder ──────────────────────────────────
def _create_tenant_schema(schema_name: str, engine):
    # TODO: expand this to also create tenant tables when ready
    with engine.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
        conn.commit()

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

    admin = User(
        username=data.admin_username,
        email=data.admin_email,
        password="",
        role="admin",
        company_id=company.id,
    )
    db.add(admin)
    db.commit()
    db.refresh(company)

    _create_tenant_schema(data.schema_name, engine)

    token = create_access_token({"sub": str(admin.id), "purpose": "set_password"})
    _send_password_set_email(data.admin_email, token)

    return company

# ─── login ────────────────────────────────────────────────────────
def login(email: str, password: str, db: Session) -> dict:
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password):
        raise AppError(status_code=401, message="Invalid credentials")

    if not user.password:
        raise AppError(status_code=403, message="Password not set yet, check your email")

    company = db.query(Company).filter(Company.id == user.company_id).first()

    token = create_access_token({
        "sub": str(user.id),
        "role": user.role,
        "company_id": str(user.company_id),
        "schema_name": company.schema_name,
    })
    return {"access_token": token, "token_type": "bearer"}

# ─── create employee ──────────────────────────────────────────────
def create_employee(data: UserCreate, admin: User, db: Session) -> User:
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise AppError(status_code=400, message="Email already registered")

    employee = User(
        username=data.username,
        email=data.email,
        password="",  # not set yet
        role=data.role,
        company_id=admin.company_id,  # taken from admin's token, not from request
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)

    token = create_access_token({"sub": str(employee.id), "purpose": "set_password"})
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
    db.commit()

    return {"message": "Password set successfully"}