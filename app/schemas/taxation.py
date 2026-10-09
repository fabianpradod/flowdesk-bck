from datetime import date
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic import field_validator
from app.taxation.domain import TAX_CATEGORIES

class TaxDefinitionInput(BaseModel):
    tax_code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=150)
    tax_type: str = "percentage"
    rate: Decimal | None = Field(default=None, ge=0)
    category: str = "TAXABLE"
    active: bool = True
    eligible_for_input_credit: bool | None = None
    withholding_type: str | None = None
    withholding_base: str | None = None
    withholding_rate: Decimal | None = Field(default=None, ge=0)
    kind: str = Field(default="OTHER", min_length=1, max_length=50)
    default_rate: Decimal | None = Field(default=None, ge=0)
    is_compound: bool = False
    priority: int = 0
    jurisdiction: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] | None = None

class TaxRuleInput(BaseModel):
    condition: dict[str, Any] | None = None
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

    @model_validator(mode="after")
    def valid_dates(self):
        if self.effective_from and self.effective_until and self.effective_until <= self.effective_from:
            raise ValueError("effective_until must be after effective_from")
        return self

class TaxProfileInput(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    description: str | None = Field(default=None, max_length=500)
    jurisdiction: str | None = Field(default=None, max_length=100)
    regime: str | None = Field(default=None, max_length=100)
    default_currency: str | None = Field(default=None, max_length=10)
    effective_from: date
    effective_until: date | None = None
    taxes: list[TaxDefinitionInput] = Field(default_factory=list)
    rules: list[TaxRuleInput] = Field(default_factory=list)
    active: bool = True
    version_id: str | None = None
    precision: int = Field(default=2, ge=0, le=12)
    rounding: str = Field(default="HALF_UP", min_length=1, max_length=20)
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def valid_dates(self):
        if self.effective_until and self.effective_until <= self.effective_from:
            raise ValueError("effective_until must be after effective_from")
        return self

class TaxProfileResponse(TaxProfileInput):
    model_config = ConfigDict(from_attributes=True)

class TaxableOperationInput(BaseModel):
    tax_amount: Decimal = Field(ge=0)
    tax_category: str
    tax_code: str | None = None
    eligible_for_input_credit: bool | None = None
    operation_date: date | None = None
    taxable_base: Decimal = Field(default=Decimal("0"), ge=0)
    document_id: Any | None = None
    tax_component_id: Any | None = None
    document_direction: str | None = None
    document_status: str | None = None
    is_calculable: bool = True
    is_withholding: bool = False
    withholding_type: str | None = None
    withholding_role: str | None = None
    applied_to: str | None = None
    withholding_effect: str | None = None
    retention_id: Any | None = None
    metadata: dict[str, Any] | None = None
    document_type: str | None = Field(default=None, max_length=50)
    currency: str | None = Field(default=None, max_length=10)
    jurisdiction: str | None = Field(default=None, max_length=100)

    @field_validator("tax_category")
    @classmethod
    def valid_category(cls, value):
        if value not in TAX_CATEGORIES:
            raise ValueError("Unsupported tax category")
        return value

class TaxCalculationRequest(BaseModel):
    as_of: date
    profile_version: str | None = Field(default=None, min_length=1, max_length=150)
    start_date: date | None = None
    end_date: date | None = None
    tax_debit: Decimal = Field(default=Decimal("0"), ge=0)
    prior_carry_forward: Decimal = Field(default=Decimal("0"), ge=0)
    operations: list[TaxableOperationInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_period(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self

class TaxCalculationResponse(BaseModel):
    tax_debit: Decimal
    tax_credit: Decimal
    net_tax: Decimal
    tax_payable: Decimal
    carry_forward: Decimal
    withholding_tax: Decimal = Decimal("0")
    details: list[dict[str, Any]]

class TaxPeriodCalculationRequest(BaseModel):
    start_date: date
    end_date: date
    prior_carry_forward: Decimal = Field(default=Decimal("0"), ge=0)
    include_details: bool = False

    @model_validator(mode="after")
    def valid_period(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self

class TaxPeriodCalculationResponse(BaseModel):
    period: dict[str, date]
    tax_debit: Decimal
    tax_credit: Decimal
    net_tax: Decimal
    tax_payable: Decimal
    carry_forward: Decimal
    withholding_tax: Decimal = Decimal("0")
    input_documents_count: int
    input_tax_components_count: int
    eligible_tax_components_count: int
    currency: str | None = None
    details: list[dict[str, Any]] = Field(default_factory=list)