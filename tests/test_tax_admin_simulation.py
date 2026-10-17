from datetime import date
from decimal import Decimal
from types import SimpleNamespace
import pytest
from app.schemas.taxation import TaxCalculationRequest, TaxProfileInput
from app.services import taxation
from app.taxation import TaxDefinition, TaxProfile, TaxRule

def profile(version="profile-v1"):
    return TaxProfile(
        jurisdiction="configured", regime=None, effective_from=date(2026, 1, 1), version_id=version,
        taxes=(TaxDefinition("TAX_A", "Configured tax", category="TAXABLE", eligible_for_input_credit=True),),
        rules=(TaxRule({"field": "tax_category", "operator": "eq", "value": "TAXABLE"}, scope="CLASSIFICATION", version_id="rule-v1", result={"direction": "INPUT", "eligible_for_input_credit": True}),),
    )

def test_profile_validation_is_non_persistent_and_reports_information(monkeypatch):
    monkeypatch.setattr(taxation, "get_tax_profiles", lambda *_args: [])
    data = TaxProfileInput(
        version_id="candidate-v1", effective_from=date(2026, 1, 1),
        taxes=[{"tax_code": "TAX_A", "name": "Configured tax", "default_rate": "10"}],
        rules=[{"scope": "CLASSIFICATION", "condition": {"field": "document_type", "operator": "eq", "value": "GENERIC"},
                "result": {"direction": "INPUT"}}],
    )
    result = taxation.validate_tax_profile(data, SimpleNamespace(), object())

    assert result["valid"] is True
    assert result["errors"] == []
    assert result["information"][0]["code"] == "deterministic_resolution"

def test_profile_validation_rejects_unknown_tax_references(monkeypatch):
    monkeypatch.setattr(taxation, "get_tax_profiles", lambda *_args: [])
    data = TaxProfileInput(
        effective_from=date(2026, 1, 1),
        taxes=[{"tax_code": "TAX_A", "name": "Configured tax"}],
        rules=[{"scope": "INPUT_TAX", "tax_code": "MISSING", "result": {"eligible_for_input_credit": True}}],
    )
    result = taxation.validate_tax_profile(data, SimpleNamespace(), object())

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "unknown_tax_code"

def test_profile_validation_rejects_invalid_declarative_condition(monkeypatch):
    monkeypatch.setattr(taxation, "get_tax_profiles", lambda *_args: [])
    data = TaxProfileInput(
        effective_from=date(2026, 1, 1), taxes=[],
        rules=[{"scope": "CLASSIFICATION", "condition": {"operator": "python", "value": "__import__('os')"}}],
    )
    result = taxation.validate_tax_profile(data, SimpleNamespace(), object())

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "invalid_configuration"

def test_simulation_can_select_a_tenant_profile_version_and_use_classifier(monkeypatch):
    selected = profile("profile-historical")
    monkeypatch.setattr(taxation, "resolve_profile_version", lambda *_args: selected)
    request = TaxCalculationRequest(
        as_of=date(2026, 7, 1), profile_version="profile-historical", tax_debit=Decimal("50"),
        operations=[{"tax_amount": "20", "tax_category": "TAXABLE", "tax_code": "TAX_A", "taxable_base": "200", "document_direction": "INPUT", "document_type": "GENERIC", "operation_date": date(2026, 6, 30)}],
    )
    result = taxation.calculate_tax(SimpleNamespace(), object(), request)

    assert result.tax_credit == Decimal("20.00")
    assert result.tax_payable == Decimal("30.00")
    assert result.details[0]["profile_version"] == "profile-historical"
    assert result.details[0]["classification_rule_version"] == "rule-v1"

def test_unknown_profile_version_is_not_leaked_or_used(monkeypatch):
    monkeypatch.setattr(taxation, "resolve_profile_version", lambda *_args: None)
    request = TaxCalculationRequest(as_of=date(2026, 7, 1), profile_version="other-tenant-version")

    with pytest.raises(Exception, match="profile"):
        taxation.calculate_tax(SimpleNamespace(), object(), request)