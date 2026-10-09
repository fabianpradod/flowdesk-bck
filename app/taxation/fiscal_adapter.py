"""Adapter from persisted fiscal-document data to the existing tax engine input."""
from decimal import Decimal
from app.taxation.domain import TaxableOperation
from app.taxation.classifier import FiscalClassifier

def document_tax_components(document: dict) -> list[dict]:
    """Return each persisted tax component once.

    Line-level components are authoritative when a document-level component is
    the same aggregate (same tax identity and amount equal to the line sum).
    Explicit component IDs are also used to eliminate exact duplicates. This
    keeps normalization separate from tax calculation and preserves distinct
    document-level taxes when they are not aggregates of line taxes.
    """
    document_components = list(document.get("taxes", []))
    line_components = [
        component

        for line in document.get("lines", [])

        for component in line.get("taxes", [])
    ]

    if not line_components:
        return document_components

    line_ids = {component.get("id") for component in line_components if component.get("id") is not None}
    line_totals: dict[tuple, object] = {}

    for component in line_components:
        key = (
            component.get("tax_code"),
            bool(component.get("is_withholding", False)),
            component.get("category") or component.get("tax_category"),
        )
        line_totals[key] = line_totals.get(key, Decimal("0")) + Decimal(str(component.get("amount", 0)))

    selected = []

    for component in document_components:
        if component.get("id") in line_ids:
            continue

        key = (
            component.get("tax_code"),
            bool(component.get("is_withholding", False)),
            component.get("category") or component.get("tax_category"),
        )

        if key in line_totals and Decimal(str(component.get("amount", 0))) == line_totals[key]:
            continue

        selected.append(component)

    return selected + line_components

def document_to_operations(document: dict, profile=None, *, classifier=None) -> list[TaxableOperation]:
    classifier = classifier or FiscalClassifier()
    components = document_tax_components(document)
    operations = []

    for component in components:
        classification = classifier.classify_component(document, component, profile) if profile else None
        operations.append(TaxableOperation(
        tax_amount=component["amount"],
        tax_category=classification.tax_category if classification and classification.tax_category else component["category"],
        taxable_base=component.get("taxable_base", 0),
        tax_code=component.get("tax_code"),
        operation_date=document.get("issue_date"),
        document_id=document.get("id"),
        tax_component_id=component.get("id"),
        document_status=document.get("status"),
        document_direction=classification.direction if classification else document.get("direction"),
        is_calculable=classification.is_calculable if classification else document.get("status") not in {"CANCELLED", "VOIDED"},
        eligible_for_input_credit=classification.eligible_for_input_credit if classification else None,
        is_withholding=component.get("is_withholding", False),
        withholding_type=component.get("withholding_type"),
        withholding_role=component.get("withholding_role"),
        applied_to=component.get("applied_to"),
        withholding_effect=component.get("withholding_effect"),
        retention_id=component.get("retention_id"),
        metadata={**(component.get("metadata") or {}), "classification": classification.as_dict()} if classification else component.get("metadata"),
        ))

    return operations