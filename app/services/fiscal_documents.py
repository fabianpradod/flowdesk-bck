"""Tenant-scoped persistence for generic fiscal input documents."""
from datetime import datetime, timezone
from uuid import uuid4, UUID
from sqlalchemy import and_, insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.schemas.fiscal import FiscalDocumentCreate, FiscalDocumentUpdate, ImportBatchCreate
from app.tenancy.runtime import get_tenant_tables, get_user_schema_name
from app.utils.exceptions import AppError

def _tables(user):
    return get_tenant_tables(get_user_schema_name(user))

def _decimal_values(data):
    return {key: value for key, value in data.items() if value is not None}

def create_import_batch(data: ImportBatchCreate, current_user, db: Session) -> dict:
    table = _tables(current_user)["import_batch"]
    batch_id = uuid4()
    payload = {"id": batch_id, **data.model_dump(exclude_none=True), "metadata_json": data.metadata}
    payload.pop("metadata", None)

    try:
        db.execute(insert(table).values(**payload))
        db.commit()

    except SQLAlchemyError as exc:
        db.rollback()

        raise AppError(status_code=500, message="Database error while creating import batch") from exc

    return {**data.model_dump(), "id": batch_id}

def create_document(data: FiscalDocumentCreate, current_user, db: Session) -> dict:
    tables = _tables(current_user)
    documents, batches = tables["fiscal_document"], tables["import_batch"]

    if data.import_batch_id is not None:
        batch = db.execute(select(batches.c.id).where(batches.c.id == data.import_batch_id)).first()

        if batch is None:
            raise AppError(status_code=404, message="Import batch not found")

    document_id = uuid4()
    now = datetime.now(timezone.utc)
    values = data.model_dump(exclude={"lines", "taxes", "metadata"}, exclude_none=True)
    values.update(id=document_id, metadata_json=data.metadata, created_at=now, updated_at=now)
    potential_duplicate = _has_potential_duplicate(db, documents, data)

    try:
        db.execute(insert(documents).values(**values))
        line_ids = []

        for line in data.lines:
            line_id = uuid4()
            line_ids.append(line_id)
            line_values = line.model_dump(exclude={"taxes"}, exclude_none=True)
            line_values.update(id=line_id, document_id=document_id)
            db.execute(insert(tables["fiscal_document_line"]).values(**line_values))

            for tax in line.taxes:
                _insert_tax(db, tables["tax_component"], document_id, tax, line_id)

        for tax in data.taxes:
            _insert_tax(db, tables["tax_component"], document_id, tax, None)

        db.commit()

    except SQLAlchemyError as exc:
        db.rollback()

        raise AppError(status_code=500, message="Database error while creating fiscal document") from exc

    return get_document(document_id, current_user, db, potential_duplicate=potential_duplicate)

def _insert_tax(db, table, document_id, tax, line_id):
    values = tax.model_dump(exclude={"metadata"})
    values.update(id=uuid4(), document_id=document_id, line_id=line_id, metadata_json=tax.metadata)
    db.execute(insert(table).values(**values))

def list_documents(current_user, db: Session, *, start_date=None, end_date=None) -> list[dict]:
    table = _tables(current_user)["fiscal_document"]
    conditions = []

    if start_date: conditions.append(table.c.issue_date >= start_date)

    if end_date: conditions.append(table.c.issue_date <= end_date)

    query = select(table).order_by(table.c.issue_date.desc(), table.c.created_at.desc())

    if conditions: query = query.where(and_(*conditions))

    return [get_document(row["id"], current_user, db) for row in db.execute(query).mappings()]

def get_document(document_id: UUID, current_user, db: Session, *, potential_duplicate=False) -> dict:
    tables = _tables(current_user)
    document = tables["fiscal_document"]
    row = db.execute(select(document).where(document.c.id == document_id)).mappings().first()

    if row is None:
        raise AppError(status_code=404, message="Fiscal document not found")

    result = dict(row)
    result["metadata"] = result.pop("metadata_json", None)
    result["potential_duplicate"] = potential_duplicate
    result["lines"] = []

    for line in db.execute(select(tables["fiscal_document_line"]).where(tables["fiscal_document_line"].c.document_id == document_id)).mappings():
        item = dict(line)
        item.pop("document_id", None)
        item["taxes"] = []

        for tax in db.execute(select(tables["tax_component"]).where(tables["tax_component"].c.line_id == item["id"])).mappings():
            item["taxes"].append(_tax_dict(tax))

        result["lines"].append(item)

    result["taxes"] = [_tax_dict(tax) for tax in db.execute(select(tables["tax_component"]).where(tables["tax_component"].c.document_id == document_id, tables["tax_component"].c.line_id.is_(None))).mappings()]
    
    return result

def _tax_dict(row):
    result = dict(row)
    result.pop("document_id", None)
    result.pop("line_id", None)
    result["metadata"] = result.pop("metadata_json", None)

    return result

def update_document(document_id: UUID, data: FiscalDocumentUpdate, current_user, db: Session) -> dict:
    table = _tables(current_user)["fiscal_document"]
    _ensure_exists(db, table, document_id)
    values = {"updated_at": datetime.now(timezone.utc)}

    if data.status is not None: values["status"] = data.status

    if data.metadata is not None: values["metadata_json"] = data.metadata

    try:
        db.execute(update(table).where(table.c.id == document_id).values(**values))
        db.commit()

    except SQLAlchemyError as exc:
        db.rollback()

        raise AppError(status_code=500, message="Database error while updating fiscal document") from exc

    return get_document(document_id, current_user, db)

def _ensure_exists(db, table, document_id):
    if db.execute(select(table.c.id).where(table.c.id == document_id)).first() is None:
        raise AppError(status_code=404, message="Fiscal document not found")

def _has_potential_duplicate(db, table, data) -> bool:
    identity = {
        "issuer_tax_identifier": data.issuer_tax_identifier,
        "document_type": data.document_type,
        "series": data.series,
        "document_number": data.document_number,
        "authorization_number": data.authorization_number,
    }

    if not identity["issuer_tax_identifier"] or not identity["document_number"]:
        return False

    conditions = [table.c[name] == value for name, value in identity.items() if value is not None]

    return db.execute(select(table.c.id).where(and_(*conditions)).limit(1)).first() is not None

def has_potential_duplicate(db, table, data) -> bool:
    return _has_potential_duplicate(db, table, data)