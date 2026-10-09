"""Tenant-scoped universal CSV/XLSX import workflow."""
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from app.schemas.fiscal import FiscalDocumentCreate, ImportMappingCreate, ImportMappingUpdate, ImportPreviewOptions
from app.services import fiscal_documents
from app.services.importer import MAX_IMPORT_FILE_BYTES, ImportFormatError, read_rows, normalize_and_validate, suggest_mapping, validate_upload
from app.tenancy.runtime import get_tenant_tables, get_user_schema_name
from app.utils.exceptions import AppError

_UPLOADS: dict[tuple[str, UUID], tuple[str, bytes]] = {}

def _tables(user): 
    return get_tenant_tables(get_user_schema_name(user))

def upload(filename, content, content_type, current_user, db):
    try: file_format = validate_upload(filename, content, content_type)
    
    except ImportFormatError: raise AppError(status_code=422, message="Invalid import file")
    
    table = _tables(current_user)["import_batch"]; batch_id = uuid4()
    payload = {"id": batch_id, "source_type": file_format, "filename": filename, "status": "UPLOADED", "total_rows": 0, "successful_rows": 0, "failed_rows": 0, "metadata_json": {"file_size": len(content)}}
    
    try: db.execute(insert(table).values(**payload)); db.commit()
    
    except SQLAlchemyError as exc:
        db.rollback(); raise AppError(status_code=500, message="Database error while creating import batch") from exc
    
    _UPLOADS[(get_user_schema_name(current_user), batch_id)] = (file_format, content)
    
    return {"id": batch_id, "filename": filename, "source_type": file_format, "status": "UPLOADED", "size": len(content)}

def preview(batch_id: UUID, options: ImportPreviewOptions, current_user, db):
    file_format, content, batch = _load(batch_id, current_user, db)
    
    try:
        profile = _mapping_config_from_id(options.mapping_id, current_user, db) if options.mapping_id else {}
        _validate_profile_for_file(profile, file_format)
        settings = _effective_options(options, profile)
        headers, rows = read_rows(content, file_format, delimiter=settings["delimiter"], sheet=settings["sheet"], encoding=settings["encoding"], header_row=settings["header_row"], data_start_row=settings["data_start_row"])
        mapping = options.mapping or profile.get("mapping") or {}
        result = normalize_and_validate(rows, mapping, locale=settings["locale"], date_format=settings["date_format"], decimal_separator=settings["decimal_separator"], thousands_separator=settings["thousands_separator"], group_by=settings["group_by"])
    
    except ImportFormatError: raise AppError(status_code=422, message="Unable to parse import file")
    
    metadata = dict(batch["metadata_json"] or {}); metadata["options"] = options.model_dump(mode="json")
    _update_batch(batch_id, {"status": "PREVIEWED", "total_rows": len(rows), "metadata_json": metadata}, current_user, db)
    
    return {"headers": headers, "detected_format": file_format, "sample_rows": rows[:20],
            "normalized_samples": [item["data"] for item in result["rows"][:20]],
            "suggested_mappings": suggest_mapping(headers),
            "mapped_fields": sorted(set(mapping.values())),
            "unmapped_columns": [header for header in headers if header not in mapping],
            "duplicate_candidates": _duplicate_candidates(result["rows"], current_user, db), **result}

def validate_batch(batch_id: UUID, options: ImportPreviewOptions, current_user, db):
    result = preview(batch_id, options, current_user, db); status = "VALIDATED" if not result["errors"] else "FAILED"
    _update_batch(batch_id, {"status": status, "failed_rows": len(result["errors"])}, current_user, db)
    
    return {"status": status, **result}

def execute(batch_id: UUID, options: ImportPreviewOptions, current_user, db):
    validation = validate_batch(batch_id, options, current_user, db)
    
    if validation["errors"]: return {"status": "FAILED", "total": validation["total"], "imported": 0, "failed": len(validation["errors"]), "duplicates": [], "warnings": validation["warnings"]}
    
    file_format, content, _ = _load(batch_id, current_user, db)
    profile = _mapping_config_from_id(options.mapping_id, current_user, db) if options.mapping_id else {}
    _validate_profile_for_file(profile, file_format)
    settings = _effective_options(options, profile)
    _, rows = read_rows(content, file_format, delimiter=settings["delimiter"], sheet=settings["sheet"], encoding=settings["encoding"], header_row=settings["header_row"], data_start_row=settings["data_start_row"])
    mapping = options.mapping or profile.get("mapping") or {}
    normalized = normalize_and_validate(rows, mapping, locale=settings["locale"], date_format=settings["date_format"], decimal_separator=settings["decimal_separator"], thousands_separator=settings["thousands_separator"], group_by=settings["group_by"])
    imported, failed, duplicates = 0, [], []
    documents = _tables(current_user)["fiscal_document"]
    
    for item in normalized["rows"]:
        if item["errors"]: continue
    
        try:
            original = {key: (value.isoformat() if hasattr(value, "isoformat") else str(value) if value is not None else None) for key, value in item.get("original", {}).items()}
            data = dict(item["data"]); data.update(source_type=file_format, import_batch_id=batch_id,
                source_row=item["row"], original_identifier=data.get("document_number"),
                metadata={"original_row": original, "source_rows": item.get("source_rows", [item["row"]]), "import_mapping_id": str(options.mapping_id) if options.mapping_id else None})
            payload = FiscalDocumentCreate.model_validate(data)
            
            if fiscal_documents.has_potential_duplicate(db, documents, payload): duplicates.append({"row": item["row"], "reason": "potential_duplicate"}); continue
            
            fiscal_documents.create_document(payload, current_user, db); imported += 1
        
        except Exception: failed.append({"row": item["row"], "reason": "invalid_document"})
    status = "IMPORTED" if not failed and not duplicates else ("PARTIAL" if imported else "FAILED")
    _update_batch(batch_id, {"status": status, "total_rows": len(rows), "successful_rows": imported, "failed_rows": len(failed)}, current_user, db)

    return {"status": status, "total": len(rows), "imported": imported, "failed": failed, "duplicates": duplicates, "warnings": normalized["warnings"]}

def create_mapping(data: ImportMappingCreate, current_user, db):
    table = _tables(current_user)["import_mapping"]; mapping_id = uuid4(); now = datetime.now(timezone.utc)
    values = data.model_dump(exclude={"metadata"}); values.update(id=mapping_id, metadata_json=data.metadata, created_at=now, updated_at=now)

    try: db.execute(insert(table).values(**values)); db.commit()

    except SQLAlchemyError as exc:
        db.rollback(); raise AppError(status_code=500, message="Database error while creating import mapping") from exc

    return {"id": mapping_id, **data.model_dump()}

def list_mappings(current_user, db):
    table = _tables(current_user)["import_mapping"]; return [_mapping_dict(row) for row in db.execute(select(table).order_by(table.c.name.asc())).mappings()]

def get_mapping(mapping_id, current_user, db):
    table = _tables(current_user)["import_mapping"]; row = db.execute(select(table).where(table.c.id == mapping_id)).mappings().first()

    if row is None: raise AppError(status_code=404, message="Import mapping not found")

    return _mapping_dict(row)

def update_mapping(mapping_id, data: ImportMappingUpdate, current_user, db):
    table = _tables(current_user)["import_mapping"]; get_mapping(mapping_id, current_user, db); values = {key: value for key, value in data.model_dump(exclude_unset=True).items() if key != "metadata"}

    if data.metadata is not None: values["metadata_json"] = data.metadata

    values["updated_at"] = datetime.now(timezone.utc); db.execute(update(table).where(table.c.id == mapping_id).values(**values)); db.commit(); return get_mapping(mapping_id, current_user, db)

def delete_mapping(mapping_id, current_user, db):
    table = _tables(current_user)["import_mapping"]; get_mapping(mapping_id, current_user, db); db.execute(table.delete().where(table.c.id == mapping_id)); db.commit()

def _mapping_from_id(mapping_id, user, db): 
    return get_mapping(mapping_id, user, db)["mapping"] if mapping_id else None

def _mapping_config_from_id(mapping_id, user, db): 
    return get_mapping(mapping_id, user, db) if mapping_id else {}

def _effective_options(options, profile):
    values = {
        "locale": options.locale or profile.get("locale"), "delimiter": options.delimiter or profile.get("delimiter"),
        "sheet": options.sheet or profile.get("sheet"), "encoding": options.encoding or profile.get("encoding"),
        "date_format": options.date_format or profile.get("date_format"),
        "decimal_separator": options.decimal_separator or profile.get("decimal_separator"),
        "thousands_separator": options.thousands_separator or profile.get("thousands_separator"),
        "header_row": options.header_row or profile.get("header_row") or 1,
        "data_start_row": options.data_start_row or profile.get("data_start_row"),
        "group_by": options.group_by or profile.get("group_by"),
    }
    return values

def _validate_profile_for_file(profile, file_format):
    if profile.get("is_active") is False:
        raise AppError(status_code=422, message="Import mapping is inactive")

    if profile.get("source_type") and profile["source_type"] != file_format:
        raise AppError(status_code=422, message="Import mapping format does not match the uploaded file")

def _duplicate_candidates(rows, user, db):
    documents = _tables(user)["fiscal_document"]
    candidates = []

    for item in rows:
        if item["errors"]:
            continue

        try:
            payload = FiscalDocumentCreate.model_validate(item["data"])

            if fiscal_documents.has_potential_duplicate(db, documents, payload):
                candidates.append({"row": item.get("row"), "source_rows": item.get("source_rows", [item.get("row")]), "reason": "potential_duplicate"})

        except Exception:
            continue

    return candidates

def _mapping_dict(row):
    result = dict(row); result["metadata"] = result.pop("metadata_json", None); return result

def _load(batch_id, user, db):
    key = (get_user_schema_name(user), batch_id)

    if key not in _UPLOADS: raise AppError(status_code=404, message="Import file is no longer available")

    table = _tables(user)["import_batch"]; batch = db.execute(select(table).where(table.c.id == batch_id)).mappings().first()

    if batch is None: raise AppError(status_code=404, message="Import batch not found")

    return (*_UPLOADS[key], batch)

def _update_batch(batch_id, values, user, db):
    table = _tables(user)["import_batch"]; db.execute(update(table).where(table.c.id == batch_id).values(**values)); db.commit()