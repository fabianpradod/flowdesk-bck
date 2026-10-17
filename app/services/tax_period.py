"""Orchestration of historical sales and persisted fiscal input documents."""
from datetime import date
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.services import analytics, fiscal_documents
from app.services.taxation import resolve_current_profile
from app.taxation import TaxEngine
from app.taxation.fiscal_adapter import document_to_operations
from app.tenancy.runtime import get_tenant_tables, get_user_schema_name
from app.utils.exceptions import AppError
from app.taxation.domain import CalculationError, TaxValidationError

def calculate_period(current_user, db: Session, *, start_date: date, end_date: date, prior_carry_forward: Decimal = Decimal("0"), include_details: bool = False) -> dict:
    if end_date < start_date:
        raise AppError(status_code=422, message="end_date must be on or after start_date")
    
    try:
        profile = resolve_current_profile(current_user, db, start_date)

        if profile is None:
            profile = resolve_current_profile(current_user, db, end_date)
    except (CalculationError, TaxValidationError, ValueError) as exc:
        raise AppError(status_code=422, message="Unable to resolve tax configuration for the requested period") from exc
    
    if profile is None:
        raise AppError(status_code=404, message="No tax profile is active for the requested period")

    def profile_for_operation(operation_date):
        resolved = resolve_current_profile(current_user, db, operation_date or start_date)
    
        if resolved is None:
            raise CalculationError("No tax profile is active for the operation date")
    
        return resolved

    debit_summary = analytics.get_fiscal_debit(current_user, db, period="custom", start_date=start_date, end_date=end_date)
    documents = get_tenant_tables(get_user_schema_name(current_user))["fiscal_document"]
    rows = db.execute(select(documents.c.id, documents.c.currency, documents.c.status, documents.c.direction).where(
        documents.c.issue_date >= start_date,
        documents.c.issue_date <= end_date,
    )).mappings()
    document_rows = [dict(row) for row in rows]
    operations = []
    participating_rows = []
    engine = TaxEngine()
    
    try:
        for row in document_rows:
            document = fiscal_documents.get_document(row["id"], current_user, db)
            document.setdefault("status", row["status"])
            document.setdefault("direction", row["direction"])
            document_profile = profile_for_operation(document.get("issue_date"))
            document_operations = [
                operation for operation in document_to_operations(document, document_profile)
                if engine.is_operation_calculable(operation, document_profile)
            ]

            if document_operations:
                participating_rows.append(row)
                operations.extend(document_operations)

        currencies = {row["currency"] for row in participating_rows if row["currency"]}

        if len(currencies) > 1:
            raise AppError(status_code=422, message="Multiple input document currencies require conversion configuration")

        result = engine.calculate_period(
            operations, profile, tax_debit=Decimal(str(debit_summary["fiscal_debit"])),
            prior_carry_forward=prior_carry_forward, start_date=start_date, end_date=end_date,
            profile_resolver=profile_for_operation,
        )
    
    except (CalculationError, TaxValidationError, ValueError) as exc:
        raise AppError(status_code=422, message="Unable to resolve tax configuration for the requested period") from exc
    
    eligible_count = sum(1 for detail in result.details if detail["eligible_for_input_credit"])
    input_document_count = sum(1 for row in participating_rows if row.get("direction") == "INPUT")
    input_component_count = sum(1 for detail in result.details if not detail.get("is_withholding") and
                                detail.get("document_direction", "INPUT") == "INPUT" and
                                (detail.get("document_id") is not None))
    payload = {
        "period": {"start": start_date, "end": end_date},
        "tax_debit": result.tax_debit, "tax_credit": result.tax_credit, "net_tax": result.net_tax,
        "tax_payable": result.tax_payable, "carry_forward": result.carry_forward,
        "withholding_tax": result.withholding_tax,
        "input_documents_count": input_document_count,
        "input_tax_components_count": input_component_count,
        "eligible_tax_components_count": eligible_count,
        "currency": next(iter(currencies), None),
        "details": list(result.details) if include_details else [],
    }
    
    return payload
