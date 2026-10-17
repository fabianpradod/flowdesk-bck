from datetime import date
from decimal import Decimal
import pytest
from app.taxation import TaxDefinition, TaxEngine, TaxProfile, TaxRule, TaxValidationError

def configured_profile(*, eligible=True):
    return TaxProfile(
        None, None, date(2026, 1, 1),
        taxes=(TaxDefinition("INPUT", "Input tax", category="TAXABLE"),),
        rules=(TaxRule(
            {"field": "tax_category", "operator": "eq", "value": "TAXABLE"},
            scope="INPUT_TAX", result={"eligible_for_input_credit": eligible},
        ),),
    )

def test_basic_credit_and_payable():
    result = TaxEngine().calculate_period([], configured_profile(), tax_debit=Decimal("100"))

    assert result.tax_debit == Decimal("100")
    assert result.tax_credit == 0 and result.net_tax == Decimal("100")
    assert result.tax_payable == Decimal("100") and result.carry_forward == 0

def test_eligible_and_non_eligible_operations_are_aggregated():
    result = TaxEngine().calculate_period([
        {"tax_amount": "100", "tax_category": "TAXABLE", "tax_code": "INPUT"},
        {"tax_amount": "50", "tax_category": "TAXABLE", "tax_code": "INPUT"},
        {"tax_amount": "25", "tax_category": "EXEMPT", "tax_code": "INPUT"},
    ], configured_profile(), tax_debit=Decimal("200"))

    assert result.tax_credit == Decimal("150")
    assert result.details[-1]["eligible_for_input_credit"] is False

def test_credit_greater_equal_and_less_than_debit():
    engine = TaxEngine()
    greater = engine.calculate_period([{"tax_amount": 200, "tax_category": "TAXABLE", "tax_code": "INPUT"}], configured_profile(), tax_debit=100, prior_carry_forward=50)
    equal = engine.calculate_period([{"tax_amount": 100, "tax_category": "TAXABLE", "tax_code": "INPUT"}], configured_profile(), tax_debit=100)
    less = engine.calculate_period([{"tax_amount": 40, "tax_category": "TAXABLE", "tax_code": "INPUT"}], configured_profile(), tax_debit=100)

    assert (greater.net_tax, greater.tax_payable, greater.carry_forward) == (Decimal("-100"), 0, Decimal("150"))
    assert (equal.net_tax, equal.tax_payable, equal.carry_forward) == (0, 0, 0)
    assert (less.net_tax, less.tax_payable, less.carry_forward) == (Decimal("60"), Decimal("60"), 0)

def test_carry_forward_is_consumed_in_next_period():
    engine = TaxEngine()
    first = engine.calculate_period([
        {"tax_amount": 150, "tax_category": "TAXABLE", "tax_code": "INPUT"}],
        configured_profile(), tax_debit=100)
    second = engine.calculate_period([
        {"tax_amount": 20, "tax_category": "TAXABLE", "tax_code": "INPUT"}],
        configured_profile(), tax_debit=80, prior_carry_forward=first.carry_forward)

    assert first.carry_forward == Decimal("50")
    assert second.tax_payable == Decimal("10") and second.carry_forward == 0

def test_exempt_and_zero_rated_keep_semantics_and_do_not_credit():
    operations = [
        {"tax_amount": 100, "tax_category": "EXEMPT", "tax_code": "INPUT"},
        {"tax_amount": 100, "tax_category": "ZERO_RATED", "tax_code": "INPUT"},
    ]
    result = TaxEngine().calculate_period(operations, configured_profile(), tax_debit=100)

    assert result.tax_credit == 0
    assert [item["tax_category"] for item in result.details] == ["EXEMPT", "ZERO_RATED"]

def test_eligibility_can_be_disabled_by_configuration_and_invalid_values_rejected():
    result = TaxEngine().calculate_period([{"tax_amount": 100, "tax_category": "TAXABLE", "tax_code": "INPUT"}], configured_profile(eligible=False), tax_debit=100)

    assert result.tax_credit == 0

    with pytest.raises(TaxValidationError):
        TaxRule(None, scope="INPUT_TAX", result={"eligible_for_input_credit": "yes"})

    with pytest.raises(TaxValidationError):
        TaxEngine().calculate_period([{"tax_amount": 1, "tax_category": "UNKNOWN"}], configured_profile())