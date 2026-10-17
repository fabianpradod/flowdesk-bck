"""Country-neutral tax value objects and a deliberately small safe rule DSL."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

ALLOWED_OPERATORS = {"eq", "neq", "gt", "gte", "lt", "lte", "in", "and", "or", "not"}
ALLOWED_CALCULATIONS = {"percentage", "fixed", "sum", "subtract", "multiply"}
TAX_CATEGORIES = {"TAXABLE", "STANDARD", "ZERO_RATED", "EXEMPT", "NON_TAXABLE", "WITHHOLDING", "OTHER"}
TAX_RULE_SCOPES = {"INPUT_TAX", "OUTPUT_TAX", "WITHHOLDING", "CLASSIFICATION", "TAX_CLASSIFICATION"}
WITHHOLDING_EFFECTS = {"REDUCE_PAYABLE", "INCREASE_CREDIT", "INFORMATIONAL"}
ALLOWED_ROUNDING = {"HALF_UP", "HALF_EVEN", "DOWN", "UP", "CEILING", "FLOOR"}

class TaxValidationError(ValueError):
    pass

class CalculationError(ValueError):
    pass

def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))

    except Exception as exc:
        raise TaxValidationError("Numeric tax values must be valid decimals") from exc

@dataclass(frozen=True)
class TaxRule:
    condition: dict[str, Any] | None
    calculation: dict[str, Any] | None = None
    tax_code: str | None = None
    active: bool = True
    priority: int = 0
    scope: str | None = None
    result: dict[str, Any] | None = None
    effective_from: date | None = None
    effective_until: date | None = None
    version_id: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self):
        if self.scope is not None and self.scope not in TAX_RULE_SCOPES:
            raise TaxValidationError("Unsupported tax rule scope")

        if self.condition is not None:
            _validate_condition(self.condition)

        if self.calculation is not None:
            _validate_calculation(self.calculation)

        if self.result is not None:
            _validate_result(self.result)

        if self.effective_from and self.effective_until and self.effective_until <= self.effective_from:
            raise TaxValidationError("Rule effective_until must be after effective_from")

        _validate_metadata(self.metadata)

    def is_effective(self, on_date: date | None) -> bool:
        if on_date is None:
            return True

        return ((self.effective_from is None or self.effective_from <= on_date) and
                (self.effective_until is None or on_date < self.effective_until))

@dataclass(frozen=True)
class TaxDefinition:
    tax_code: str
    name: str
    tax_type: str = "percentage"
    rate: Decimal | None = None
    category: str = "TAXABLE"
    active: bool = True
    eligible_for_input_credit: bool | None = None
    withholding_type: str | None = None
    withholding_base: str | None = None
    withholding_rate: Decimal | None = None
    kind: str = "OTHER"
    default_rate: Decimal | None = None
    is_compound: bool = False
    priority: int = 0
    jurisdiction: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self):
        if not self.tax_code or not self.name:
            raise TaxValidationError("Tax code and name are required")

        if self.category not in TAX_CATEGORIES:
            raise TaxValidationError("Unsupported tax category")

        for rate in (self.rate, self.default_rate, self.withholding_rate):
            if rate is not None and _decimal(rate) < 0:
                raise TaxValidationError("Tax rates cannot be negative")

        if self.tax_type == "percentage" and self.rate is not None and _decimal(self.rate) < 0:
            raise TaxValidationError("Percentage rates cannot be negative")

        _validate_metadata(self.metadata)

    @property
    def effective_rate(self) -> Decimal | None:
        return self.default_rate if self.default_rate is not None else self.rate

@dataclass(frozen=True)
class TaxProfile:
    jurisdiction: str | None
    regime: str | None
    effective_from: date
    effective_until: date | None = None
    taxes: tuple[TaxDefinition, ...] = field(default_factory=tuple)
    rules: tuple[TaxRule, ...] = field(default_factory=tuple)
    active: bool = True
    version_id: str | None = None
    name: str | None = None
    description: str | None = None
    default_currency: str | None = None
    precision: int = 2
    rounding: str = "HALF_UP"
    metadata: dict[str, Any] | None = None

    def __post_init__(self):
        if self.effective_until and self.effective_until <= self.effective_from:
            raise TaxValidationError("effective_until must be after effective_from")

        codes = [tax.tax_code for tax in self.taxes]

        if len(codes) != len(set(codes)):
            raise TaxValidationError("Tax codes must be unique within a profile")

        _validate_rule_ranges(self.rules)

        if self.precision < 0 or self.precision > 12:
            raise TaxValidationError("Tax precision must be between 0 and 12")

        if self.rounding not in ALLOWED_ROUNDING:
            raise TaxValidationError("Unsupported tax rounding mode")

        _validate_metadata(self.metadata)

@dataclass(frozen=True)
class TaxCalculation:
    tax_debit: Decimal = Decimal("0")
    tax_credit: Decimal = Decimal("0")
    net_tax: Decimal = Decimal("0")
    tax_payable: Decimal = Decimal("0")
    carry_forward: Decimal = Decimal("0")
    details: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    withholding_tax: Decimal = Decimal("0")

@dataclass(frozen=True)
class TaxableOperation:
    """In-memory input contract for future fiscal documents; never persisted."""
    tax_amount: Decimal
    tax_category: str
    taxable_base: Decimal = Decimal("0")
    tax_code: str | None = None
    eligible_for_input_credit: bool | None = None
    operation_date: date | None = None
    document_id: Any | None = None
    tax_component_id: Any | None = None
    document_status: str | None = None
    document_direction: str | None = None
    is_calculable: bool = True
    is_withholding: bool = False
    withholding_type: str | None = None
    withholding_role: str | None = None
    applied_to: str | None = None
    withholding_effect: str | None = None
    retention_id: Any | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self):
        if _decimal(self.tax_amount) < 0:
            raise TaxValidationError("Tax amounts cannot be negative")

        if self.tax_category not in TAX_CATEGORIES:
            raise TaxValidationError("Unsupported tax category")

        if self.is_withholding and self.withholding_effect is not None and self.withholding_effect not in WITHHOLDING_EFFECTS:
            raise TaxValidationError("Unsupported withholding effect")

        _validate_metadata(self.metadata)

def resolve_profile(profiles: list[TaxProfile] | tuple[TaxProfile, ...], on_date: date) -> TaxProfile | None:
    candidates = [p for p in profiles if p.active and p.effective_from <= on_date and (p.effective_until is None or on_date < p.effective_until)]
    # Persisted profiles are validated for overlap before they are stored.
    # Legacy tenants may contain an older open-ended version; a later version
    # implicitly supersedes it for compatibility. Bounded overlaps are errors.

    if len(candidates) > 1 and all(profile.effective_until is not None for profile in candidates):
        raise TaxValidationError("Multiple tax profiles are effective for the requested date")

    return max(candidates, key=lambda p: p.effective_from, default=None)

def validate_profile_versions(profiles: list[TaxProfile] | tuple[TaxProfile, ...]) -> None:
    active = [profile for profile in profiles if profile.active]

    for index, left in enumerate(active):
        for right in active[index + 1:]:
            if (left.jurisdiction, left.regime) != (right.jurisdiction, right.regime):
                continue

            if _ranges_overlap(left.effective_from, left.effective_until, right.effective_from, right.effective_until):
                raise TaxValidationError("Tax profile versions cannot overlap for the same scope")

def _validate_condition(condition: dict[str, Any]) -> None:
    operator = condition.get("operator")

    if operator not in ALLOWED_OPERATORS:
        raise TaxValidationError("Unsupported condition operator")

    if operator in {"and", "or"}:
        values = condition.get("conditions")

        if not isinstance(values, list) or not values:
            raise TaxValidationError("and/or require conditions")

        for value in values:
            _validate_condition(value)

    elif operator == "not":
        _validate_condition(condition.get("condition", {}))

    elif "field" not in condition or "value" not in condition:
        raise TaxValidationError("A comparison requires field and value")

def _validate_calculation(calculation: dict[str, Any]) -> None:
    kind = calculation.get("type")

    if kind not in ALLOWED_CALCULATIONS:
        raise TaxValidationError("Unsupported calculation type")

    if kind in {"percentage", "fixed"} and "value" not in calculation and "rate" not in calculation:
        raise TaxValidationError("Calculation requires value or rate")

    if kind in {"sum", "subtract", "multiply"} and not isinstance(calculation.get("operands"), list):
        raise TaxValidationError("Arithmetic calculations require operands")

def _validate_result(result: dict[str, Any]) -> None:
    allowed = {"eligible_for_input_credit", "is_calculable", "withholding_effect", "withholding_type", "withholding_role", "applied_to", "tax_rate", "tax_category", "tax_code", "direction", "metadata"}

    if set(result) - allowed:
        raise TaxValidationError("Unsupported tax rule result")

    if "eligible_for_input_credit" in result and not isinstance(result["eligible_for_input_credit"], bool):
        raise TaxValidationError("Eligibility result must be boolean")

    if "is_calculable" in result and not isinstance(result["is_calculable"], bool):
        raise TaxValidationError("Calculability result must be boolean")

    if "withholding_effect" in result and result["withholding_effect"] not in WITHHOLDING_EFFECTS:
        raise TaxValidationError("Unsupported withholding effect")

    for field_name in ("withholding_type", "withholding_role", "applied_to"):
        if field_name in result and not isinstance(result[field_name], str):
            raise TaxValidationError(f"{field_name} must be a string")

    if "tax_rate" in result and _decimal(result["tax_rate"]) < 0:
        raise TaxValidationError("Tax rule rates cannot be negative")

    if "tax_category" in result and result["tax_category"] not in TAX_CATEGORIES:
        raise TaxValidationError("Unsupported tax rule category")

    if "direction" in result and result["direction"] not in {"INPUT", "OUTPUT"}:
        raise TaxValidationError("Unsupported fiscal direction")

    if "tax_code" in result and not isinstance(result["tax_code"], str):
        raise TaxValidationError("Tax rule tax_code must be a string")

    _validate_metadata(result.get("metadata"))

def _validate_rule_ranges(rules: tuple[TaxRule, ...]) -> None:
    keyed = {}

    for rule in rules:
        key = (rule.scope, rule.tax_code, rule.priority)

        for previous in keyed.get(key, []):
            if _ranges_overlap(rule.effective_from, rule.effective_until, previous.effective_from, previous.effective_until):
                raise TaxValidationError("Tax rules with the same scope and priority cannot overlap")
        
        keyed.setdefault(key, []).append(rule)

def _ranges_overlap(left_start, left_end, right_start, right_end) -> bool:
    left_start = left_start or date.min
    right_start = right_start or date.min
    left_finish = left_end
    right_finish = right_end

    return ((left_finish is None or right_start < left_finish) and (right_finish is None or left_start < right_finish))

def _validate_metadata(metadata: dict[str, Any] | None, *, depth: int = 0) -> None:
    if metadata is None:
        return

    if not isinstance(metadata, dict) or depth > 5:
        raise TaxValidationError("Tax metadata must be a bounded JSON object")

    if len(metadata) > 100:
        raise TaxValidationError("Tax metadata has too many keys")

    for value in metadata.values():
        if isinstance(value, dict):
            _validate_metadata(value, depth=depth + 1)

        elif isinstance(value, list) and len(value) > 100:
            raise TaxValidationError("Tax metadata arrays are too large")

def field_value(context: dict[str, Any], field: str):
    """Resolve only dotted dictionary paths from declarative context."""
    value: Any = context

    for part in field.split("."):
        if not isinstance(value, dict):
            return None

        value = value.get(part)

    return value