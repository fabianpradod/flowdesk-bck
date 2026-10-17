import uuid
from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from app.models.tenant.base import Base, TENANT_SCHEMA

class ImportBatch(Base):
    __tablename__ = "import_batch"
    __table_args__ = {"schema": TENANT_SCHEMA}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type = Column(String(50), nullable=False)
    filename = Column(String(255), nullable=True)
    imported_at = Column(DateTime, nullable=False, server_default=text("now()"))
    status = Column(String(30), nullable=False, server_default=text("'PENDING'"))
    total_rows = Column(Integer, nullable=False, server_default=text("0"))
    successful_rows = Column(Integer, nullable=False, server_default=text("0"))
    failed_rows = Column(Integer, nullable=False, server_default=text("0"))
    metadata_json = Column(JSON, nullable=True)

class ImportMapping(Base):
    __tablename__ = "import_mapping"
    __table_args__ = {"schema": TENANT_SCHEMA}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(150), nullable=False)
    description = Column(String(500), nullable=True)
    source_type = Column(String(20), nullable=False)
    mapping = Column(JSON, nullable=False)
    locale = Column(String(20), nullable=True)
    delimiter = Column(String(1), nullable=True)
    sheet = Column(String(150), nullable=True)
    encoding = Column(String(50), nullable=True)
    date_format = Column(String(20), nullable=True)
    decimal_separator = Column(String(1), nullable=True)
    thousands_separator = Column(String(1), nullable=True)
    header_row = Column(Integer, nullable=False, server_default=text("1"))
    data_start_row = Column(Integer, nullable=True)
    group_by = Column(JSON, nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("now()"))

class FiscalDocument(Base):
    __tablename__ = "fiscal_document"
    __table_args__ = (
        CheckConstraint("subtotal >= 0", name="ck_fiscal_document_subtotal_nonnegative"),
        CheckConstraint("taxable_base >= 0", name="ck_fiscal_document_taxable_base_nonnegative"),
        CheckConstraint("total_tax >= 0", name="ck_fiscal_document_total_tax_nonnegative"),
        CheckConstraint("total >= 0", name="ck_fiscal_document_total_nonnegative"),
        {"schema": TENANT_SCHEMA},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_type = Column(String(50), nullable=False)
    direction = Column(String(20), nullable=False, server_default=text("'INPUT'"))
    issue_date = Column(Date, nullable=False)
    document_number = Column(String(100), nullable=True)
    series = Column(String(100), nullable=True)
    authorization_number = Column(String(150), nullable=True)
    issuer_name = Column(String(200), nullable=True)
    issuer_tax_identifier = Column(String(150), nullable=True)
    issuer_tax_identifier_type = Column(String(50), nullable=True)
    receiver_name = Column(String(200), nullable=True)
    receiver_tax_identifier = Column(String(150), nullable=True)
    receiver_tax_identifier_type = Column(String(50), nullable=True)
    currency = Column(String(10), nullable=False)
    subtotal = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    taxable_base = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    total_tax = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    total = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    status = Column(String(30), nullable=False, server_default=text("'DRAFT'"))
    jurisdiction = Column(String(100), nullable=True)
    source_type = Column(String(50), nullable=True)
    source_identifier = Column(String(255), nullable=True)
    import_batch_id = Column(UUID(as_uuid=True), ForeignKey(f"{TENANT_SCHEMA}.import_batch.id"), nullable=True)
    source_row = Column(Integer, nullable=True)
    original_identifier = Column(String(255), nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("now()"))

class FiscalDocumentLine(Base):
    __tablename__ = "fiscal_document_line"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_fiscal_document_line_quantity_nonnegative"),
        CheckConstraint("unit_price >= 0", name="ck_fiscal_document_line_unit_price_nonnegative"),
        CheckConstraint("taxable_base >= 0", name="ck_fiscal_document_line_taxable_base_nonnegative"),
        CheckConstraint("total >= 0", name="ck_fiscal_document_line_total_nonnegative"),
        {"schema": TENANT_SCHEMA},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey(f"{TENANT_SCHEMA}.fiscal_document.id"), nullable=False)
    description = Column(String(500), nullable=True)
    quantity = Column(Numeric(18, 6), nullable=True)
    unit_price = Column(Numeric(18, 6), nullable=True)
    taxable_base = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    total = Column(Numeric(18, 2), nullable=False, server_default=text("0"))

class TaxComponent(Base):
    __tablename__ = "tax_component"
    __table_args__ = (
        CheckConstraint("taxable_base >= 0", name="ck_tax_component_base_nonnegative"),
        CheckConstraint("amount >= 0", name="ck_tax_component_amount_nonnegative"),
        CheckConstraint("rate >= 0", name="ck_tax_component_rate_nonnegative"),
        {"schema": TENANT_SCHEMA},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey(f"{TENANT_SCHEMA}.fiscal_document.id"), nullable=False)
    line_id = Column(UUID(as_uuid=True), ForeignKey(f"{TENANT_SCHEMA}.fiscal_document_line.id"), nullable=True)
    tax_code = Column(String(50), nullable=False)
    tax_name = Column(String(150), nullable=True)
    tax_type = Column(String(50), nullable=False)
    category = Column(String(30), nullable=False)
    rate = Column(Numeric(18, 8), nullable=True)
    taxable_base = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    is_withholding = Column(Boolean, nullable=False, server_default=text("false"))
    retention_id = Column(String(150), nullable=True)
    withholding_type = Column(String(50), nullable=True)
    withholding_role = Column(String(50), nullable=True)
    applied_to = Column(String(50), nullable=True)
    withholding_effect = Column(String(30), nullable=True)
    metadata_json = Column(JSON, nullable=True)