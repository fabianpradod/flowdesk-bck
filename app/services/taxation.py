"""Tenant-scoped persistence for the generic tax profile document."""
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.schemas.taxation import TaxCalculationRequest, TaxProfileInput, TaxRuleInput
from app.taxation import CalculationError, FiscalClassifier, TaxDefinition, TaxEngine, TaxProfile, TaxRule, TaxValidationError, resolve_profile, validate_profile_versions
from app.tenancy.runtime import get_tenant_tables, get_user_schema_name
from app.utils.exceptions import AppError

def _tables(user):
    return get_tenant_tables(get_user_schema_name(user))

def _profile_from_input(data: TaxProfileInput, *, version_id: str | None = None) -> TaxProfile:
    return TaxProfile(name=data.name, description=data.description,
        jurisdiction=data.jurisdiction, regime=data.regime, default_currency=data.default_currency,
        effective_from=data.effective_from, effective_until=data.effective_until,
        active=data.active,
        taxes=tuple(TaxDefinition(**tax.model_dump()) for tax in data.taxes),
        rules=tuple(TaxRule(**rule.model_dump()) for rule in data.rules),
        version_id=data.version_id or version_id or str(uuid4()), precision=data.precision,
        rounding=data.rounding, metadata=data.metadata)

def _serialize(profile: TaxProfile) -> dict:
    def clean(value):
        if isinstance(value, Decimal): return str(value)
        
        if isinstance(value, date): return value.isoformat()
        
        if isinstance(value, tuple): return [clean(v) for v in value]
        
        if isinstance(value, dict): return {k: clean(v) for k, v in value.items()}
        
        if hasattr(value, "__dataclass_fields__"):
            return {k: clean(getattr(value, k)) for k in value.__dataclass_fields__}
        
        return value
    
    return clean(profile)

def get_tax_profile(current_user, db: Session) -> dict:
    table = _tables(current_user)["configuracion_tributaria"]
    row = db.execute(select(table.c.perfil_tributario).order_by(table.c.updated_at.desc()).limit(1)).first()
    payload = row[0] if row and row[0] else None
    
    return payload or {"profiles": []}

def resolve_current_profile(current_user, db: Session, on_date: date) -> TaxProfile | None:
    profiles = get_tax_profiles(current_user, db)

    return resolve_profile(profiles, on_date)

def resolve_profile_version(current_user, db: Session, version_id: str) -> TaxProfile | None:
    return next((profile for profile in get_tax_profiles(current_user, db) if profile.version_id == version_id), None)

def get_tax_profiles(current_user, db: Session) -> list[TaxProfile]:
    return [_deserialize_profile(payload) for payload in get_tax_profile(current_user, db).get("profiles", [])]

def _deserialize_profile(payload: dict) -> TaxProfile:
    data = TaxProfileInput.model_validate(payload)

    return TaxProfile(
        name=data.name, description=data.description,
        jurisdiction=data.jurisdiction, regime=data.regime, default_currency=data.default_currency,
        effective_from=data.effective_from, effective_until=data.effective_until,
        active=data.active,
        taxes=tuple(TaxDefinition(**tax.model_dump()) for tax in data.taxes),
        rules=tuple(TaxRule(**rule.model_dump()) for rule in data.rules),
        version_id=data.version_id,
        precision=data.precision, rounding=data.rounding, metadata=data.metadata,
    )

def calculate_tax(current_user, db: Session, request: TaxCalculationRequest):
    profile = (resolve_profile_version(current_user, db, request.profile_version) if request.profile_version else resolve_current_profile(current_user, db, request.as_of))
    
    if profile is None:
        raise AppError(status_code=404, message="No tax profile is active for the requested date or version")
    
    try:
        classifier = FiscalClassifier()

        def classified_operations():
            for operation in request.operations:
                payload = operation.model_dump()
                # Preserve the legacy simulation contract when the caller sends
                # a bare TaxableOperation rather than document-like data.
    
                if not payload.get("document_direction") and not payload.get("document_type"):
                    yield payload
                    continue
    
                operation_date = payload.get("operation_date") or request.as_of
                operation_profile = profile if request.profile_version else resolve_current_profile(current_user, db, operation_date)
    
                if operation_profile is None:
                    raise CalculationError("No tax profile is active for the operation date")
    
                component = {"tax_code": payload.get("tax_code"), "category": payload.get("tax_category"),
                             "amount": payload.get("tax_amount"), "taxable_base": payload.get("taxable_base"),
                             "is_withholding": payload.get("is_withholding", False),
                             "withholding_type": payload.get("withholding_type"),
                             "withholding_role": payload.get("withholding_role"),
                             "withholding_effect": payload.get("withholding_effect")}
                synthetic_document = {"id": payload.get("document_id"),
                    "document_type": payload.get("document_type"), "direction": payload.get("document_direction"),
                    "issue_date": operation_date, "status": payload.get("document_status") or "ACTIVE",
                    "currency": payload.get("currency"), "jurisdiction": payload.get("jurisdiction"),
                    "metadata": payload.get("metadata"), "taxes": [component], "lines": []}
                classification = classifier.classify_component(synthetic_document, component, operation_profile)
                payload.update(tax_category=classification.tax_category or payload["tax_category"],
                               document_direction=classification.direction,
                               eligible_for_input_credit=classification.eligible_for_input_credit,
                               is_calculable=classification.is_calculable,
                               metadata={**(payload.get("metadata") or {}), "classification": classification.as_dict()})
    
                yield payload

        def profile_for_operation(operation_date):
            resolved = profile if request.profile_version else resolve_current_profile(current_user, db, operation_date or request.as_of)
    
            if resolved is None:
                raise CalculationError("No tax profile is active for the operation date")
    
            return resolved

        return TaxEngine().calculate_period(
            classified_operations(), profile,
            tax_debit=request.tax_debit, prior_carry_forward=request.prior_carry_forward,
            start_date=request.start_date, end_date=request.end_date,
            profile_resolver=profile_for_operation,
        )
    
    except (TaxValidationError, CalculationError, ValueError):
        raise AppError(status_code=422, message="Invalid tax calculation input")

def validate_tax_profile(data: TaxProfileInput, current_user, db: Session) -> dict:
    errors, warnings, information = [], [], []

    try:
        candidate = _profile_from_input(data)
        existing = get_tax_profiles(current_user, db)
        validate_profile_versions(existing + [candidate])
        tax_codes = {tax.tax_code for tax in candidate.taxes}

        for rule in candidate.rules:
            if rule.tax_code and rule.tax_code not in tax_codes:
                errors.append({"code": "unknown_tax_code", "tax_code": rule.tax_code})

        if not candidate.taxes:
            warnings.append({"code": "profile_without_tax_definitions"})

        if not candidate.rules:
            warnings.append({"code": "profile_without_rules"})

        information.append({"code": "deterministic_resolution", "message": "Profile and rules passed declarative validation"})

    except (TaxValidationError, ValueError) as exc:
        errors.append({"code": "invalid_configuration", "message": str(exc)})

    return {"valid": not errors, "errors": errors, "warnings": warnings, "information": information}

def put_tax_profile(data: TaxProfileInput, current_user, db: Session, *, _allow_version_update: bool = False) -> dict:
    try:
        profile = _profile_from_input(data)

    except (TaxValidationError, ValueError):
        raise AppError(status_code=422, message="Invalid tax profile")

    table = _tables(current_user)["configuracion_tributaria"]
    now = datetime.now(timezone.utc)
    current = db.execute(select(table.c.id, table.c.perfil_tributario).order_by(table.c.updated_at.desc()).limit(1)).first()
    versions = list((current[1] or {}).get("profiles", []) if current else [])
    same_start = [item for item in versions if item.get("effective_from") == data.effective_from.isoformat()]

    if same_start and not _allow_version_update:
        existing_id = same_start[0].get("version_id")

        if existing_id or data.version_id:
            raise AppError(status_code=409, message="Historical tax profile versions are immutable; create a new version")

    versions = [item for item in versions if item.get("effective_from") != data.effective_from.isoformat()]

    for item in versions:
        if (item.get("jurisdiction"), item.get("regime")) != (data.jurisdiction, data.regime):
            continue

        if item.get("effective_until") is None and item.get("effective_from", "") < data.effective_from.isoformat():
            item["effective_until"] = data.effective_from.isoformat()

    versions.append(_serialize(profile))

    try:
        validate_profile_versions([_deserialize_profile(item) for item in versions])

    except (TaxValidationError, ValueError) as exc:
        raise AppError(status_code=422, message="Overlapping or invalid tax profile versions") from exc

    payload = {"profiles": sorted(versions, key=lambda item: item["effective_from"])}

    try:
        if current:
            db.execute(update(table).where(table.c.id == current[0]).values(perfil_tributario=payload, updated_at=now))
        else:
            db.execute(insert(table).values(id=uuid4(), tasa_impuesto=Decimal("0"), perfil_tributario=payload, created_at=now, updated_at=now))

        db.commit()

    except SQLAlchemyError as exc:
        db.rollback()

        raise AppError(status_code=500, message="Database error while updating tax profile") from exc

    return payload

def list_tax_rules(current_user, db: Session) -> list[dict]:
    return [rule for profile in get_tax_profile(current_user, db).get("profiles", []) for rule in profile.get("rules", [])]

def create_tax_rule(data: TaxRuleInput, current_user, db: Session) -> dict:
    if data.effective_from is None:
        raise AppError(status_code=422, message="effective_from is required when creating a tax rule")

    profiles = get_tax_profile(current_user, db).get("profiles", [])

    if not profiles:
        raise AppError(status_code=400, message="Create a tax profile before adding rules")

    latest = max(profiles, key=lambda item: item["effective_from"])

    try:
        TaxRule(**data.model_dump())

    except TaxValidationError:
        raise AppError(status_code=422, message="Invalid tax rule")

    rule = {"id": str(uuid4()), **data.model_dump()}
    latest.setdefault("rules", []).append(rule)

    return put_tax_profile(TaxProfileInput.model_validate(latest), current_user, db, _allow_version_update=True) | {"rule": rule}