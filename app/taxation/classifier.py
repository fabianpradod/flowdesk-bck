"""Declarative, country-neutral classification of persisted fiscal documents."""
from dataclasses import dataclass
from datetime import date
from typing import Any
from app.taxation.domain import TAX_CATEGORIES, TaxProfile, TaxRule, TaxValidationError
from app.taxation.engine import TaxEngine

CLASSIFICATION_SCOPES = {"CLASSIFICATION", "TAX_CLASSIFICATION"}
NON_CALCULABLE_STATUSES = {"CANCELLED", "VOIDED"}

@dataclass(frozen=True)
class ClassificationResult:
    document_id: Any | None
    direction: str | None
    tax_category: str | None
    tax_code: str | None
    taxable_base: Any | None
    is_calculable: bool
    eligible_for_input_credit: bool | None = None
    reason: str | None = None
    rule_version: str | None = None
    profile_version: str | None = None
    effective_from: date | None = None
    effective_until: date | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "direction": self.direction,
            "tax_category": self.tax_category,
            "tax_code": self.tax_code,
            "taxable_base": self.taxable_base,
            "is_calculable": self.is_calculable,
            "eligible_for_input_credit": self.eligible_for_input_credit,
            "reason": self.reason,
            "rule_version": self.rule_version,
            "profile_version": self.profile_version,
            "effective_from": self.effective_from,
            "effective_until": self.effective_until,
        }

class FiscalClassifier:
    """Resolves classification rules; it never calculates tax amounts."""

    def classify(self, document: dict[str, Any], profile: TaxProfile, *, at_date: date | None = None) -> ClassificationResult:
        return self._resolve(document, profile, at_date=at_date)

    def classify_component(self, document: dict[str, Any], component: dict[str, Any], profile: TaxProfile, *, at_date: date | None = None) -> ClassificationResult:
        return self._resolve(document, profile, component=component, at_date=at_date)

    def _resolve(self, document, profile, *, component=None, at_date=None):
        operation_date = at_date or document.get("issue_date")
        context = _classification_context(document, component)
        direction = document.get("direction")
        category = component.get("category") if component else _document_category(document)
        tax_code = component.get("tax_code") if component else None
        taxable_base = component.get("taxable_base") if component else document.get("taxable_base")
        is_calculable = document.get("status") not in NON_CALCULABLE_STATUSES
        eligible = None
        matches = [rule for rule in profile.rules
                   if rule.active and rule.scope in CLASSIFICATION_SCOPES and rule.is_effective(operation_date)
                   and (rule.tax_code in (None, tax_code))
                   and (rule.condition is None or TaxEngine()._condition(rule.condition, context))]
        matches.sort(key=lambda rule: rule.priority)
        selected = matches[0] if matches else None

        if selected:
            same_priority = [rule for rule in matches if rule.priority == selected.priority]

            if len({_classification_result_signature(rule) for rule in same_priority}) > 1:
                raise TaxValidationError("Ambiguous fiscal classification rules")

        if selected:
            result = selected.result or {}
            direction = result.get("direction", direction)
            category = result.get("tax_category", category)
            tax_code = result.get("tax_code", tax_code)

            if "is_calculable" in result:
                is_calculable = bool(result["is_calculable"])

            eligible = result.get("eligible_for_input_credit")

        reason = None

        if document.get("status") in NON_CALCULABLE_STATUSES:
            reason = "DOCUMENT_STATUS_NOT_CALCULABLE"

        elif direction not in {"INPUT", "OUTPUT"}:
            is_calculable, reason = False, "MISSING_REQUIRED_FIELD"

        elif category is None:
            is_calculable, reason = False, "NO_APPLICABLE_RULE"

        elif category not in TAX_CATEGORIES:
            is_calculable, reason = False, "INVALID_DATA"

        elif category == "NON_TAXABLE":
            reason = "NON_TAXABLE_OPERATION"

        elif category == "EXEMPT":
            reason = "EXEMPT_CATEGORY"

        elif not is_calculable and document.get("status") not in NON_CALCULABLE_STATUSES:
            reason = "NO_APPLICABLE_RULE"

        return ClassificationResult(
            document_id=document.get("id"), direction=direction, tax_category=category,
            tax_code=tax_code, taxable_base=taxable_base, is_calculable=is_calculable,
            eligible_for_input_credit=eligible, reason=reason,
            rule_version=selected.version_id if selected else None,
            profile_version=profile.version_id, effective_from=profile.effective_from,
            effective_until=profile.effective_until,
        )

def _classification_context(document: dict[str, Any], component: dict[str, Any] | None) -> dict[str, Any]:
    context = dict(document)
    context["metadata"] = document.get("metadata")
    context["tax_components"] = list(document.get("taxes", []))
    context["issuer"] = {"name": document.get("issuer_name"), "tax_identifier": document.get("issuer_tax_identifier"), "tax_identifier_type": document.get("issuer_tax_identifier_type")}
    context["receiver"] = {"name": document.get("receiver_name"), "tax_identifier": document.get("receiver_tax_identifier"), "tax_identifier_type": document.get("receiver_tax_identifier_type")}

    if component:
        context.update(component)
        context["tax_category"] = component.get("category")
        context["tax_code"] = component.get("tax_code")
        context["tax_amount"] = component.get("amount")
        context["taxable_base"] = component.get("taxable_base", document.get("taxable_base"))

    return context

def _document_category(document: dict[str, Any]) -> str | None:
    categories = {component.get("category") for component in _all_components(document) if not component.get("is_withholding") and component.get("category")}
    
    return next(iter(categories)) if len(categories) == 1 else None

def _all_components(document):
    components = list(document.get("taxes", []))

    for line in document.get("lines", []):
        components.extend(line.get("taxes", []))

    return components

def _classification_result_signature(rule: TaxRule):
    result = rule.result or {}

    return tuple(sorted((key, repr(value)) for key, value in result.items()))