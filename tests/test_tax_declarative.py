from datetime import date
from decimal import Decimal
import pytest
from app.taxation import TaxDefinition, TaxEngine, TaxProfile, TaxRule, TaxValidationError

def test_profile_and_tax_definitions_support_generic_metadata_and_multiple_taxes():
    profile = TaxProfile(
        None, None, date(2026, 1, 1),
        name="Configurable profile", description="Generic configuration",
        default_currency="USD", precision=2, rounding="HALF_UP",
        metadata={"source": "tenant-config"},
        taxes=(
            TaxDefinition("TAX_A", "Tax A", kind="CONSUMPTION", default_rate=Decimal("10"), priority=1, metadata={"group": "primary"}),
            TaxDefinition("TAX_B", "Tax B", kind="OTHER", default_rate=Decimal("5"), priority=2),
        ),
        rules=(
            TaxRule(None, tax_code="TAX_A"),
            TaxRule(None, tax_code="TAX_B"),
        ),
    )
    result = TaxEngine().calculate({"taxable_base": Decimal("100")}, profile)

    assert result.tax_debit == Decimal("15.00")
    assert [detail["tax_code"] for detail in result.details] == ["TAX_A", "TAX_B"]
    assert profile.metadata == {"source": "tenant-config"}

def test_compound_taxes_use_deterministic_priority_and_previous_tax():
    profile = TaxProfile(
        None, None, date(2026, 1, 1),
        taxes=(
            TaxDefinition("A", "A", default_rate=Decimal("10"), priority=1),
            TaxDefinition("B", "B", default_rate=Decimal("5"), is_compound=True, priority=2),
        ),
        rules=(TaxRule(None, tax_code="A"), TaxRule(None, tax_code="B")),
    )
    result = TaxEngine().calculate({"taxable_base": Decimal("100")}, profile)

    assert result.tax_debit == Decimal("15.50")
    assert result.details[1]["taxable_base"] == Decimal("110.00")

def test_categories_preserve_zero_exempt_and_non_taxable_semantics():
    profile = TaxProfile(
        None, None, date(2026, 1, 1),
        taxes=(
            TaxDefinition("STANDARD", "Standard", category="STANDARD", default_rate=Decimal("10")),
            TaxDefinition("ZERO", "Zero", category="ZERO_RATED", default_rate=Decimal("10")),
            TaxDefinition("EXEMPT", "Exempt", category="EXEMPT", default_rate=Decimal("10")),
            TaxDefinition("OUT", "Outside", category="NON_TAXABLE", default_rate=Decimal("10")),
        ),
        rules=tuple(TaxRule(None, tax_code=code) for code in ("STANDARD", "ZERO", "EXEMPT", "OUT")),
    )
    result = TaxEngine().calculate({"taxable_base": Decimal("100")}, profile)

    assert result.tax_debit == Decimal("10.00")
    assert [detail["tax_code"] for detail in result.details] == ["STANDARD"]

def test_rule_result_can_override_generic_tax_rate_and_category():
    profile = TaxProfile(
        None, None, date(2026, 1, 1),
        taxes=(TaxDefinition("CONFIGURED", "Configured", default_rate=Decimal("2")),),
        rules=(TaxRule(None, tax_code="CONFIGURED", result={"tax_rate": "7", "tax_code": "DERIVED"}),),
    )
    result = TaxEngine().calculate({"taxable_base": Decimal("100")}, profile)

    assert result.tax_debit == Decimal("7.00")
    assert result.details[0]["tax_code"] == "DERIVED"
    assert result.details[0]["tax_rate"] == Decimal("7")

def test_configurable_rounding_uses_decimal_not_float():
    profile = TaxProfile(
        None, None, date(2026, 1, 1), precision=1, rounding="HALF_UP",
        taxes=(TaxDefinition("TAX", "Tax", tax_type="fixed"),),
        rules=(TaxRule(None, tax_code="TAX", calculation={"type": "fixed", "value": "1.55"}),),
    )

    assert TaxEngine().calculate({"taxable_base": Decimal("1")}, profile).tax_debit == Decimal("1.6")

def test_metadata_limits_are_rejected():
    with pytest.raises(TaxValidationError):
        TaxProfile(None, None, date(2026, 1, 1), metadata={"nested": {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}})