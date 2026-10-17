from datetime import date
from decimal import Decimal
import pytest
from app.taxation import FiscalClassifier, TaxDefinition, TaxProfile, TaxRule, TaxValidationError, TaxEngine
from app.taxation.fiscal_adapter import document_to_operations

def profile_with_classification(*rules):
    return TaxProfile(
        jurisdiction="configured",
        regime=None,
        effective_from=date(2026, 1, 1),
        version_id="profile-v1",
        taxes=(TaxDefinition("TAX_A", "Configured tax", category="TAXABLE"),),
        rules=tuple(rules),
    )

def document(**overrides):
    value = {
        "id": "document-1", "document_type": "INVOICE", "direction": "INPUT",
        "issue_date": date(2026, 3, 15), "currency": "USD", "status": "ACTIVE",
        "taxable_base": Decimal("100"), "taxes": [{"id": "component-1", "tax_code": "TAX_A",
        "category": "TAXABLE", "amount": Decimal("10"), "taxable_base": Decimal("100")}],
        "lines": [],
    }

    value.update(overrides)

    return value

def test_classification_resolves_direction_category_and_credit_declaratively():
    profile = profile_with_classification(TaxRule(
        {"field": "document_type", "operator": "eq", "value": "INVOICE"},
        scope="CLASSIFICATION", version_id="rule-v1",
        result={"direction": "INPUT", "tax_category": "STANDARD", "eligible_for_input_credit": True},
    ))
    result = FiscalClassifier().classify(document(), profile)

    assert result.direction == "INPUT"
    assert result.tax_category == "STANDARD"
    assert result.eligible_for_input_credit is True
    assert result.rule_version == "rule-v1"
    assert result.profile_version == "profile-v1"

def test_adapter_preserves_component_snapshot_and_carries_classification_to_engine():
    profile = profile_with_classification(TaxRule(
        {"field": "tax_category", "operator": "eq", "value": "TAXABLE"},
        scope="CLASSIFICATION", result={"eligible_for_input_credit": True},
    ))
    operations = document_to_operations(document(), profile)

    assert operations[0].tax_amount == Decimal("10")
    assert operations[0].taxable_base == Decimal("100")
    assert operations[0].eligible_for_input_credit is True

    result = TaxEngine().calculate_period(operations, profile, tax_debit=Decimal("20"))

    assert result.tax_credit == Decimal("10")

def test_classification_respects_effective_until_exclusive_and_versions():
    first = TaxRule(None, scope="CLASSIFICATION", version_id="rule-a", effective_from=date(2026, 1, 1), effective_until=date(2026, 7, 1), result={"tax_category": "ZERO_RATED"})
    second = TaxRule(None, scope="CLASSIFICATION", version_id="rule-b", effective_from=date(2026, 7, 1), result={"tax_category": "EXEMPT"})
    profile = profile_with_classification(first, second)
    classifier = FiscalClassifier()

    assert classifier.classify(document(issue_date=date(2026, 6, 30)), profile).tax_category == "ZERO_RATED"
    assert classifier.classify(document(issue_date=date(2026, 7, 1)), profile).tax_category == "EXEMPT"
    assert classifier.classify(document(issue_date=date(2026, 7, 1)), profile).rule_version == "rule-b"

def test_line_components_keep_distinct_categories_without_document_recalculation():
    profile = profile_with_classification()
    operations = document_to_operations(document(
        taxes=[],
        lines=[{"taxes": [
            {"id": "a", "tax_code": "TAX_A", "category": "ZERO_RATED", "amount": Decimal("0")},
            {"id": "b", "tax_code": "TAX_A", "category": "EXEMPT", "amount": Decimal("0")},
        ]}],
    ), profile)

    assert [operation.tax_category for operation in operations] == ["ZERO_RATED", "EXEMPT"]

def test_invalid_classification_result_is_rejected_by_safe_dsl():
    with pytest.raises(TaxValidationError):
        TaxRule(None, scope="CLASSIFICATION", result={"direction": "COUNTRY_SPECIFIC"})

def test_missing_category_is_explicitly_not_calculable():
    result = FiscalClassifier().classify(document(taxes=[], lines=[]), profile_with_classification())

    assert result.is_calculable is False
    assert result.reason == "NO_APPLICABLE_RULE"