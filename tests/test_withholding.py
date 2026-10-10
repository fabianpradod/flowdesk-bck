from datetime import date
from decimal import Decimal
import pytest
from app.services.importer import normalize_and_validate
from app.taxation import TaxDefinition, TaxEngine, TaxProfile, TaxRule, TaxValidationError
from app.taxation.fiscal_adapter import document_to_operations

def withholding_profile(*rules):
    return TaxProfile(
        None, None, date(2026, 1, 1),
        taxes=(TaxDefinition("TAX", "Configured tax"),),
        rules=tuple(rules),
    )

def withholding_operation(amount="50", **overrides):
    operation = {
        "tax_amount": amount,
        "tax_category": "TAXABLE",
        "tax_code": "TAX",
        "taxable_base": "1000",
        "is_withholding": True,
        "withholding_type": "configured_type",
        "withholding_role": "SUBJECT",
        "applied_to": "TAX",
        "retention_id": "ret-1",
    }
    operation.update(overrides)

    return operation

def test_withholding_is_separate_from_normal_tax_and_can_reduce_payable():
    profile = withholding_profile(TaxRule(
        {"field": "is_withholding", "operator": "eq", "value": True},
        scope="WITHHOLDING", result={"withholding_effect": "REDUCE_PAYABLE"},
    ))
    result = TaxEngine().calculate_period([withholding_operation()], profile, tax_debit=100)

    assert result.tax_debit == Decimal("100")
    assert result.tax_credit == Decimal("0")
    assert result.withholding_tax == Decimal("50.00")
    assert result.net_tax == Decimal("100")
    assert result.tax_payable == Decimal("50")
    assert result.details[0]["is_withholding"] is True

def test_withholding_without_rule_is_informational_and_not_credit():
    result = TaxEngine().calculate_period([withholding_operation()], withholding_profile(), tax_debit=100)

    assert result.withholding_tax == Decimal("50.00")
    assert result.tax_credit == 0
    assert result.tax_payable == Decimal("100")
    assert result.details[0]["withholding_effect"] == "INFORMATIONAL"

def test_withholding_can_be_configured_as_credit_without_becoming_input_credit():
    profile = withholding_profile(TaxRule(
        None, scope="WITHHOLDING", result={"withholding_effect": "INCREASE_CREDIT"},
    ))
    result = TaxEngine().calculate_period([withholding_operation("150")], profile, tax_debit=100)

    assert result.tax_credit == 0
    assert result.withholding_tax == Decimal("150.00")
    assert result.tax_payable == 0
    assert result.carry_forward == Decimal("50")

def test_adapter_preserves_withholding_snapshot_and_direction():
    operations = document_to_operations({
        "id": "document-1", "direction": "OUTPUT", "status": "ACTIVE",
        "issue_date": date(2026, 1, 15), "lines": [],
        "taxes": [{
            "id": "component-1", "tax_code": "TAX", "tax_category": "TAXABLE",
            "category": "TAXABLE", "amount": Decimal("50"), "taxable_base": Decimal("1000"),
            "is_withholding": True, "withholding_type": "configured_type",
            "withholding_role": "WITHHOLDER", "applied_to": "TAX",
            "withholding_effect": "INFORMATIONAL", "retention_id": "ret-1",
        }],
    })

    assert operations[0].is_withholding is True
    assert operations[0].document_direction == "OUTPUT"
    assert operations[0].retention_id == "ret-1"

def test_import_mapping_normalizes_multiple_withholdings_without_country_rules():
    rows = [{
        "Document": "INVOICE", "Date": "2026-01-15", "Currency": "USD",
        "Code 1": "TAX", "Type 1": "configured_type", "Amount 1": "50",
        "Withholding 1": "true", "Code 2": "OTHER", "Amount 2": "10",
        "Withholding 2": "1",
    }]
    mapping = {
        "Document": "document_type", "Date": "issue_date", "Currency": "currency",
        "Code 1": "taxes[0].tax_code", "Type 1": "taxes[0].withholding_type",
        "Amount 1": "taxes[0].amount", "Withholding 1": "taxes[0].is_withholding",
        "Code 2": "taxes[1].tax_code", "Amount 2": "taxes[1].amount",
        "Withholding 2": "taxes[1].is_withholding",
    }
    result = normalize_and_validate(rows, mapping)
    taxes = result["rows"][0]["data"]["taxes"]

    assert not result["errors"]
    assert taxes[0]["is_withholding"] is True
    assert taxes[1]["amount"] == Decimal("10")

def test_withholding_effect_is_restricted_to_safe_declarative_values():
    with pytest.raises(TaxValidationError):
        TaxRule(None, scope="WITHHOLDING", result={"withholding_effect": "PYTHON"})