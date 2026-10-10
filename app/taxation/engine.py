"""Safe interpreter for the supported declarative tax rule subset."""

from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP
from typing import Any, Callable, Iterable
from app.taxation.domain import CalculationError, TaxCalculation, TaxProfile, TaxableOperation, _decimal, field_value

class TaxEngine:
    def calculate(self, transaction: dict[str, Any], tax_profile: TaxProfile, date=None, *, at_date=None) -> TaxCalculation:
        evaluation_date = at_date or date
        debit = Decimal("0")
        details = []
        base = _decimal(transaction.get("taxable_base", transaction.get("gross_amount", 0)))
        previous_tax = Decimal("0")

        for tax in sorted(tax_profile.taxes, key=lambda definition: definition.priority):
            if not tax.active or tax.category in {"EXEMPT", "ZERO_RATED", "NON_TAXABLE", "WITHHOLDING"}:
                continue

            context = dict(transaction)
            context["taxable_base"] = base + previous_tax if tax.is_compound else base
            rules = sorted((r for r in tax_profile.rules if r.active and r.is_effective(evaluation_date) and
                            r.scope in (None, "OUTPUT_TAX", "TAX_CLASSIFICATION") and
                            (r.tax_code in (None, tax.tax_code))), key=lambda r: r.priority)
            matched = False

            for rule in rules:
                if rule.condition is None or self._condition(rule.condition, context):
                    matched = True
                    result = rule.result or {}
                    category = result.get("tax_category", tax.category)

                    if category in {"EXEMPT", "ZERO_RATED", "NON_TAXABLE", "WITHHOLDING"}:
                        break

                    code = result.get("tax_code", tax.tax_code)
                    rate = _decimal(result["tax_rate"]) if "tax_rate" in result else tax.effective_rate
                    calculation = rule.calculation

                    if calculation is None and rate is not None:
                        calculation = {"type": "percentage", "rate": rate}

                    if calculation is None:
                        break

                    amount = self._calculation(calculation, context, rate or Decimal("0"))
                    amount = _quantize(amount, tax_profile)
                    debit += amount
                    previous_tax += amount
                    details.append({"tax_code": code, "amount": amount, "tax_rate": rate,
                                    "taxable_base": context["taxable_base"], "category": category,
                                    "profile_version": tax_profile.version_id,
                                    "effective_from": tax_profile.effective_from,
                                    "effective_until": tax_profile.effective_until})
                    break

            if not matched and tax.effective_rate is not None:
                amount = self._calculation({"type": "percentage", "rate": tax.effective_rate},
                                           context, tax.effective_rate)
                amount = _quantize(amount, tax_profile)
                debit += amount
                previous_tax += amount
                details.append({"tax_code": tax.tax_code, "amount": amount,
                                "tax_rate": tax.effective_rate, "taxable_base": context["taxable_base"],
                                "category": tax.category, "profile_version": tax_profile.version_id,
                                "effective_from": tax_profile.effective_from,
                                "effective_until": tax_profile.effective_until})
        debit = _quantize(debit, tax_profile)
        credit = max(Decimal("0"), Decimal(str(transaction.get("tax_credit", "0"))))
        net = debit - credit

        return TaxCalculation(tax_debit=debit, tax_credit=credit, net_tax=net,
                              tax_payable=max(net, Decimal("0")), carry_forward=max(-net, Decimal("0")),
                              details=tuple(details))

    def calculate_period(self, operations: Iterable[TaxableOperation | dict[str, Any]], tax_profile: TaxProfile, *,
                         tax_debit: Decimal = Decimal("0"), prior_carry_forward: Decimal = Decimal("0"),
                         start_date: date | None = None, end_date: date | None = None,
                         profile_resolver: Callable[[date | None], TaxProfile | None] | None = None) -> TaxCalculation:
        """Calculate configured input credit without persisting fiscal documents."""
        debit = _non_negative(tax_debit, "tax_debit")
        prior = _non_negative(prior_carry_forward, "prior_carry_forward")
        current_credit = Decimal("0")
        withholding_tax = Decimal("0")
        payable_reductions = Decimal("0")
        withholding_credit = Decimal("0")
        details = []

        for raw in operations:
            operation = raw if isinstance(raw, TaxableOperation) else TaxableOperation(
                tax_amount=_decimal(raw.get("tax_amount", 0)), tax_category=raw.get("tax_category"),
                taxable_base=_decimal(raw.get("taxable_base", 0)),
                tax_code=raw.get("tax_code"), eligible_for_input_credit=raw.get("eligible_for_input_credit"),
                operation_date=raw.get("operation_date"), document_id=raw.get("document_id"),
                tax_component_id=raw.get("tax_component_id"), document_status=raw.get("document_status"),
                document_direction=raw.get("document_direction"), is_calculable=raw.get("is_calculable", True),
                is_withholding=raw.get("is_withholding", False), withholding_type=raw.get("withholding_type"),
                withholding_role=raw.get("withholding_role"), applied_to=raw.get("applied_to"),
                withholding_effect=raw.get("withholding_effect"), retention_id=raw.get("retention_id"),
                metadata=raw.get("metadata"))

            if start_date and operation.operation_date and operation.operation_date < start_date: continue

            if end_date and operation.operation_date and operation.operation_date > end_date: continue

            operation_profile = (profile_resolver(operation.operation_date) if profile_resolver else tax_profile)

            if operation_profile is None:
                raise CalculationError("No tax profile is active for the operation date")

            if operation.is_withholding:
                calculable, effect = self._withholding_semantics(operation, operation_profile)

                if calculable:
                    withholding_tax += _decimal(operation.tax_amount)

                    if effect == "REDUCE_PAYABLE": payable_reductions += _decimal(operation.tax_amount)

                    if effect == "INCREASE_CREDIT": withholding_credit += _decimal(operation.tax_amount)

                eligible = False
                details.append({"tax_amount": _decimal(operation.tax_amount), "taxable_base": _decimal(operation.taxable_base),
                                "tax_category": operation.tax_category, "tax_code": operation.tax_code,
                                "eligible_for_input_credit": eligible, "is_withholding": True,
                                "withholding_effect": effect if calculable else "INFORMATIONAL",
                                "withholding_type": operation.withholding_type,
                                "withholding_role": operation.withholding_role, "applied_to": operation.applied_to,
                                "retention_id": operation.retention_id,
                                "document_id": operation.document_id, "tax_component_id": operation.tax_component_id,
                                "document_direction": operation.document_direction,
                                "classification_reason": (operation.metadata or {}).get("classification", {}).get("reason"),
                                "classification_rule_version": (operation.metadata or {}).get("classification", {}).get("rule_version"),
                                "profile_version": operation_profile.version_id,
                                "effective_from": operation_profile.effective_from,
                                "effective_until": operation_profile.effective_until})

                continue

            eligible = self._input_credit_eligibility(operation, operation_profile)

            if eligible: current_credit += _decimal(operation.tax_amount)

            details.append({"tax_amount": _decimal(operation.tax_amount), "taxable_base": _decimal(operation.taxable_base), "tax_category": operation.tax_category,
                            "tax_code": operation.tax_code, "eligible_for_input_credit": eligible, "is_withholding": False,
                            "document_id": operation.document_id, "tax_component_id": operation.tax_component_id,
                            "document_direction": operation.document_direction,
                            "classification_reason": (operation.metadata or {}).get("classification", {}).get("reason"),
                            "classification_rule_version": (operation.metadata or {}).get("classification", {}).get("rule_version"),
                            "profile_version": operation_profile.version_id,
                            "effective_from": operation_profile.effective_from,
                            "effective_until": operation_profile.effective_until})
        current_credit = _quantize(current_credit, tax_profile)
        withholding_tax = _quantize(withholding_tax, tax_profile)
        effective_credit = current_credit + withholding_credit
        available = effective_credit + prior
        net = debit - current_credit
        payable = max(debit - available - payable_reductions, Decimal("0"))

        return TaxCalculation(tax_debit=debit, tax_credit=current_credit, net_tax=net,
                              tax_payable=payable, carry_forward=max(available - debit, Decimal("0")),
                              details=tuple(details), withholding_tax=withholding_tax)

    def _input_credit_eligibility(self, operation: TaxableOperation, profile: TaxProfile) -> bool:
        context = {"tax_amount": operation.tax_amount, "tax_category": operation.tax_category,
                   "taxable_base": operation.taxable_base,
                   "tax_code": operation.tax_code, "eligible_for_input_credit": operation.eligible_for_input_credit,
                   "document_status": operation.document_status, "document_direction": operation.document_direction,
                   "is_withholding": operation.is_withholding, "metadata": operation.metadata}

        if operation.document_direction == "OUTPUT":
            return False

        rules = sorted((rule for rule in profile.rules if rule.active and rule.is_effective(operation.operation_date) and
                        rule.scope == "INPUT_TAX" and rule.tax_code in (None, operation.tax_code)), key=lambda rule: rule.priority)

        calculable = operation.is_calculable

        for rule in rules:
            if rule.condition is None or self._condition(rule.condition, context):
                if "is_calculable" in (rule.result or {}):
                    calculable = bool(rule.result["is_calculable"])
                    break

        if not calculable:
            return False

        for rule in rules:
            if rule.condition is None or self._condition(rule.condition, context):
                if "eligible_for_input_credit" in (rule.result or {}):
                    return bool(rule.result["eligible_for_input_credit"])

        if operation.eligible_for_input_credit is not None:
            return bool(operation.eligible_for_input_credit)

        return next((tax.eligible_for_input_credit is True for tax in profile.taxes if tax.tax_code == operation.tax_code), False)

    def _withholding_semantics(self, operation: TaxableOperation, profile: TaxProfile) -> tuple[bool, str]:
        context = {"tax_amount": operation.tax_amount, "taxable_base": operation.taxable_base,
                   "tax_category": operation.tax_category, "tax_code": operation.tax_code,
                   "document_status": operation.document_status, "document_direction": operation.document_direction,
                   "is_withholding": True, "withholding_type": operation.withholding_type,
                   "withholding_role": operation.withholding_role, "applied_to": operation.applied_to,
                   "metadata": operation.metadata}
        rules = sorted((rule for rule in profile.rules if rule.active and rule.is_effective(operation.operation_date) and
                        rule.scope == "WITHHOLDING" and rule.tax_code in (None, operation.tax_code)), key=lambda rule: rule.priority)
        calculable = operation.is_calculable
        effect = operation.withholding_effect or "INFORMATIONAL"

        for rule in rules:
            if rule.condition is None or self._condition(rule.condition, context):
                result = rule.result or {}

                if "is_calculable" in result:
                    calculable = bool(result["is_calculable"])

                if "withholding_effect" in result:
                    effect = result["withholding_effect"]

                break

        return calculable, effect

    def _condition(self, condition, context):
        operator = condition["operator"]

        if operator in {"and", "or"}:
            values = [self._condition(c, context) for c in condition["conditions"]]

            return all(values) if operator == "and" else any(values)

        if operator == "not":
            return not self._condition(condition["condition"], context)

        left, right = field_value(context, condition["field"]), condition["value"]

        if isinstance(left, Decimal) and not isinstance(right, Decimal):
            try: right = Decimal(str(right))

            except Exception: pass

        if operator == "in": return left in right if right is not None else False

        if left is None:
            return operator == "neq" and right is not None

        comparisons = {
            "eq": lambda: left == right,
            "neq": lambda: left != right,
            "gt": lambda: left > right,
            "gte": lambda: left >= right,
            "lt": lambda: left < right,
            "lte": lambda: left <= right,
        }

        if operator not in comparisons:
            raise CalculationError(f"Unsupported condition operator: {operator}")

        return comparisons[operator]()

    def _calculation(self, calculation, context, default_rate):
        kind = calculation["type"]

        if kind == "percentage":
            rate = Decimal(str(calculation.get("rate", calculation.get("value", default_rate or 0))))

            return Decimal(str(context.get("taxable_base", 0))) * rate / Decimal("100")

        if kind == "fixed": return Decimal(str(calculation.get("value", calculation.get("rate", 0))))

        values = [self._calculation(v, context, default_rate) if isinstance(v, dict) else Decimal(str(v)) for v in calculation["operands"]]

        if kind == "sum": return sum(values, Decimal("0"))

        if kind == "subtract":
            if not values: raise CalculationError("subtract requires operands")

            return values[0] - sum(values[1:], Decimal("0"))

        result = Decimal("1")

        for value in values: result *= value

        return result

def _non_negative(value: Decimal, name: str) -> Decimal:
    value = _decimal(value)

    if value < 0: raise CalculationError(f"{name} cannot be negative")

    return value

def _quantize(value: Decimal, profile: TaxProfile) -> Decimal:
    rounding = {
        "HALF_UP": ROUND_HALF_UP, "HALF_EVEN": ROUND_HALF_EVEN, "DOWN": ROUND_DOWN,
        "UP": ROUND_UP, "CEILING": ROUND_CEILING, "FLOOR": ROUND_FLOOR,
    }[profile.rounding]

    return value.quantize(Decimal("1").scaleb(-profile.precision), rounding=rounding)