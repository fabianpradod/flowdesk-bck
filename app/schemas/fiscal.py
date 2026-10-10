from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, model_validator
from app.taxation.domain import TAX_CATEGORIES, WITHHOLDING_EFFECTS

FiscalStatus = Literal["ACTIVE", "CANCELLED", "VOIDED", "DRAFT"]

class TaxComponentInput(BaseModel):
    tax_code: str = Field(min_length=1, max_length=50)
    tax_name: str | None = Field(default=None, max_length=150)
    tax_type: str = Field(min_length=1, max_length=50)
    category: str
    rate: Decimal | None = Field(default=None, ge=0)
    taxable_base: Decimal = Field(default=Decimal("0"), ge=0)
    amount: Decimal = Field(default=Decimal("0"), ge=0)
    is_withholding: bool = False
    retention_id: str | None = Field(default=None, max_length=150)
    withholding_type: str | None = Field(default=None, max_length=50)
    withholding_role: str | None = Field(default=None, max_length=50)
    applied_to: str | None = Field(default=None, max_length=50)
    withholding_effect: str | None = Field(default=None, max_length=30)
    metadata: dict[str, Any] | None = None

    @field_validator("category")
    @classmethod
    def valid_category(cls, value):
        if value not in TAX_CATEGORIES:
            raise ValueError("Unsupported tax category")
        
        return value

    @field_validator("withholding_effect")
    @classmethod
    def valid_withholding_effect(cls, value):
        if value is not None and value not in WITHHOLDING_EFFECTS:
            raise ValueError("Unsupported withholding effect")
        
        return value

class FiscalDocumentLineInput(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    quantity: Decimal | None = Field(default=None, ge=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    taxable_base: Decimal = Field(default=Decimal("0"), ge=0)
    total: Decimal = Field(default=Decimal("0"), ge=0)
    taxes: list[TaxComponentInput] = Field(default_factory=list)

class FiscalDocumentCreate(BaseModel):
    document_type: str = Field(min_length=1, max_length=50)
    direction: Literal["INPUT", "OUTPUT"] = "INPUT"
    issue_date: date
    document_number: str | None = Field(default=None, max_length=100)
    series: str | None = Field(default=None, max_length=100)
    authorization_number: str | None = Field(default=None, max_length=150)
    issuer_name: str | None = Field(default=None, max_length=200)
    issuer_tax_identifier: str | None = Field(default=None, max_length=150)
    issuer_tax_identifier_type: str | None = Field(default=None, max_length=50)
    receiver_name: str | None = Field(default=None, max_length=200)
    receiver_tax_identifier: str | None = Field(default=None, max_length=150)
    receiver_tax_identifier_type: str | None = Field(default=None, max_length=50)
    currency: str = Field(min_length=1, max_length=10)
    subtotal: Decimal = Field(default=Decimal("0"), ge=0)
    taxable_base: Decimal = Field(default=Decimal("0"), ge=0)
    total_tax: Decimal = Field(default=Decimal("0"), ge=0)
    total: Decimal = Field(default=Decimal("0"), ge=0)
    status: FiscalStatus = "DRAFT"
    jurisdiction: str | None = Field(default=None, max_length=100)
    source_type: str | None = Field(default=None, max_length=50)
    source_identifier: str | None = Field(default=None, max_length=255)
    import_batch_id: UUID | None = None
    source_row: int | None = Field(default=None, ge=1)
    original_identifier: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] | None = None
    taxes: list[TaxComponentInput] = Field(default_factory=list)
    lines: list[FiscalDocumentLineInput] = Field(default_factory=list)

class FiscalDocumentUpdate(BaseModel):
    status: FiscalStatus | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def has_changes(self):
        if self.status is None and self.metadata is None:
            raise ValueError("At least one controlled field must be provided")

        return self

class FiscalDocumentResponse(BaseModel):
    id: UUID
    document_type: str
    direction: str
    issue_date: date
    document_number: str | None
    series: str | None
    authorization_number: str | None
    issuer_name: str | None
    issuer_tax_identifier: str | None
    issuer_tax_identifier_type: str | None
    receiver_name: str | None
    receiver_tax_identifier: str | None
    receiver_tax_identifier_type: str | None
    currency: str
    subtotal: Decimal
    taxable_base: Decimal
    total_tax: Decimal
    total: Decimal
    status: str
    jurisdiction: str | None
    source_type: str | None
    source_identifier: str | None
    import_batch_id: UUID | None
    source_row: int | None
    original_identifier: str | None
    metadata: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    potential_duplicate: bool = False
    lines: list[dict[str, Any]] = Field(default_factory=list)
    taxes: list[dict[str, Any]] = Field(default_factory=list)

class ImportBatchCreate(BaseModel):
    source_type: str = Field(min_length=1, max_length=50)
    filename: str | None = Field(default=None, max_length=255)
    status: str = Field(default="PENDING", min_length=1, max_length=30)
    total_rows: int = Field(default=0, ge=0)
    successful_rows: int = Field(default=0, ge=0)
    failed_rows: int = Field(default=0, ge=0)
    metadata: dict[str, Any] | None = None

class ImportMappingCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=500)
    source_type: Literal["CSV", "XLSX"]
    mapping: dict[str, str]
    locale: str | None = Field(default=None, max_length=20)
    delimiter: str | None = Field(default=None, min_length=1, max_length=1)
    sheet: str | None = Field(default=None, max_length=150)
    encoding: str | None = Field(default=None, max_length=50)
    date_format: Literal["DMY", "MDY", "YMD"] | None = None
    decimal_separator: str | None = Field(default=None, min_length=1, max_length=1)
    thousands_separator: str | None = Field(default=None, min_length=1, max_length=1)
    header_row: int = Field(default=1, ge=1)
    data_start_row: int | None = Field(default=None, ge=1)
    group_by: list[str] | None = None
    is_active: bool = True
    metadata: dict[str, Any] | None = None

class ImportMappingUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=500)
    mapping: dict[str, str] | None = None
    locale: str | None = Field(default=None, max_length=20)
    delimiter: str | None = Field(default=None, min_length=1, max_length=1)
    sheet: str | None = Field(default=None, max_length=150)
    encoding: str | None = Field(default=None, max_length=50)
    date_format: Literal["DMY", "MDY", "YMD"] | None = None
    decimal_separator: str | None = Field(default=None, min_length=1, max_length=1)
    thousands_separator: str | None = Field(default=None, min_length=1, max_length=1)
    header_row: int | None = Field(default=None, ge=1)
    data_start_row: int | None = Field(default=None, ge=1)
    group_by: list[str] | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None

class ImportPreviewOptions(BaseModel):
    mapping_id: UUID | None = None
    mapping: dict[str, str] | None = None
    locale: str | None = Field(default=None, max_length=20)
    delimiter: str | None = Field(default=None, min_length=1, max_length=1)
    sheet: str | None = Field(default=None, max_length=150)
    encoding: str | None = Field(default=None, max_length=50)
    date_format: Literal["DMY", "MDY", "YMD"] | None = None
    decimal_separator: str | None = Field(default=None, min_length=1, max_length=1)
    thousands_separator: str | None = Field(default=None, min_length=1, max_length=1)
    header_row: int | None = Field(default=None, ge=1)
    data_start_row: int | None = Field(default=None, ge=1)
    group_by: list[str] | None = None