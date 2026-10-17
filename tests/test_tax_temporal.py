from datetime import date
from decimal import Decimal
import pytest
from app.taxation import TaxDefinition, TaxEngine, TaxProfile, TaxRule, TaxValidationError, resolve_profile, validate_profile_versions

def profile(start, end, *, rules=(), version_id=None):
    return TaxProfile(
        None, None, start, effective_until=end,
        taxes=(TaxDefinition("INPUT", "Configured input tax"),),
        rules=tuple(rules), version_id=version_id,
    )

def eligibility_rule(start, end, eligible):
    return TaxRule(
        {"field": "tax_category", "operator": "eq", "value": "TAXABLE"},
        scope="INPUT_TAX", result={"eligible_for_input_credit": eligible},
        effective_from=start, effective_until=end,
    )

def test_profile_resolution_uses_exclusive_effective_until():
    first = profile(date(2026, 1, 1), date(2026, 7, 1), version_id="v1")
    second = profile(date(2026, 7, 1), None, version_id="v2")

    assert resolve_profile([first, second], date(2026, 6, 30)) is first
    assert resolve_profile([first, second], date(2026, 7, 1)) is second
    assert resolve_profile([first, second], date(2027, 1, 1)) is second
    assert resolve_profile([first, second], date(2025, 12, 31)) is None

def test_profile_overlap_is_rejected_before_persistence():
    first = profile(date(2026, 1, 1), date(2026, 8, 1))
    second = profile(date(2026, 7, 1), None)

    with pytest.raises(TaxValidationError, match="cannot overlap"):
        validate_profile_versions([first, second])

def test_rules_are_resolved_using_operation_date_not_current_date():
    old = profile(
        date(2026, 1, 1), date(2026, 7, 1),
        rules=(eligibility_rule(date(2026, 1, 1), date(2026, 7, 1), True),),
    )
    current = profile(
        date(2026, 7, 1), None,
        rules=(eligibility_rule(date(2026, 7, 1), None, False),),
    )
    resolver = lambda operation_date: old if operation_date < date(2026, 7, 1) else current
    result = TaxEngine().calculate_period([
        {"tax_amount": "40", "tax_category": "TAXABLE", "tax_code": "INPUT", "operation_date": date(2026, 5, 10)},
        {"tax_amount": "30", "tax_category": "TAXABLE", "tax_code": "INPUT", "operation_date": date(2026, 8, 10)},
    ], old, tax_debit=100, profile_resolver=resolver)

    assert result.tax_credit == Decimal("40.00")
    assert result.details[0]["profile_version"] is None
    assert result.details[1]["eligible_for_input_credit"] is False

def test_withholding_rule_uses_operation_date():
    old = profile(
        date(2026, 1, 1), date(2026, 7, 1),
        rules=(TaxRule(None, scope="WITHHOLDING", result={"withholding_effect": "REDUCE_PAYABLE"},
                       effective_from=date(2026, 1, 1), effective_until=date(2026, 7, 1)),),
    )
    current = profile(
        date(2026, 7, 1), None,
        rules=(TaxRule(None, scope="WITHHOLDING", result={"withholding_effect": "INFORMATIONAL"},
                       effective_from=date(2026, 7, 1)),),
    )
    resolver = lambda operation_date: old if operation_date < date(2026, 7, 1) else current
    result = TaxEngine().calculate_period([
        {"tax_amount": "20", "tax_category": "TAXABLE", "tax_code": "INPUT",
         "operation_date": date(2026, 6, 30), "is_withholding": True},
        {"tax_amount": "30", "tax_category": "TAXABLE", "tax_code": "INPUT",
         "operation_date": date(2026, 7, 1), "is_withholding": True},
    ], old, tax_debit=100, profile_resolver=resolver)

    assert result.withholding_tax == Decimal("50.00")
    assert result.tax_payable == Decimal("80")