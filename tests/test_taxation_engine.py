from datetime import date
from decimal import Decimal
import pytest
from app.taxation import TaxDefinition, TaxEngine, TaxProfile, TaxRule, TaxValidationError, resolve_profile

def profile(*, category="TAXABLE", rate="10", rules=None):
    return TaxProfile(None, None, date(2026, 1, 1), taxes=(TaxDefinition("TAX", "Configurable tax", rate=Decimal(rate), category=category),), rules=tuple(rules or (TaxRule(None, {"type": "percentage", "rate": Decimal(rate)}),)))

def test_percentage_and_zero_rated_calculation():
    assert TaxEngine().calculate({"taxable_base": Decimal("100")}, profile()).tax_debit == Decimal("10.00")
    assert TaxEngine().calculate({"taxable_base": Decimal("100")}, profile(category="ZERO_RATED")).tax_debit == 0

def test_exempt_is_not_same_as_an_accidental_zero_rule():
    result = TaxEngine().calculate({"taxable_base": Decimal("100")}, profile(category="EXEMPT"))

    assert result.tax_debit == 0 and result.details == ()

def test_engine_preserves_carry_forward_when_credit_exceeds_debit():
    result = TaxEngine().calculate({"taxable_base": Decimal("100"), "tax_credit": "20"}, profile())

    assert result.net_tax == Decimal("-10.00") and result.tax_payable == 0 and result.carry_forward == Decimal("10")

def test_invalid_operator_and_calculation_are_rejected():
    with pytest.raises(TaxValidationError):
        TaxRule({"field": "taxable_base", "operator": "python"}, {"type": "percentage", "value": 1})

    with pytest.raises(TaxValidationError):
        TaxRule(None, {"type": "eval", "value": 1})

def test_profile_resolution_is_temporal_and_deterministic():
    first = profile()
    second = TaxProfile(None, None, date(2026, 7, 1), taxes=first.taxes, rules=first.rules)

    assert resolve_profile([first, second], date(2026, 3, 1)) is first
    assert resolve_profile([first, second], date(2026, 7, 1)) is second
    assert resolve_profile([first], date(2025, 12, 31)) is None
    assert resolve_profile([first], date(2027, 1, 1)) is first