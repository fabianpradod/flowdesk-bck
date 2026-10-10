from datetime import date
from uuid import UUID
from fastapi import APIRouter, Depends, File, UploadFile, Query
from sqlalchemy.orm import Session
from app.api.dependencies.auth import get_db, require_role
from app.models.users import User
from app.schemas.taxation import TaxCalculationRequest, TaxCalculationResponse, TaxPeriodCalculationRequest, TaxPeriodCalculationResponse, TaxProfileInput, TaxRuleInput
from app.schemas.fiscal import FiscalDocumentCreate, FiscalDocumentResponse, FiscalDocumentUpdate, ImportBatchCreate, ImportMappingCreate, ImportMappingUpdate, ImportPreviewOptions
from app.services import fiscal_documents
from app.services import imports
from app.services import taxation as service
from app.services import tax_period

router = APIRouter(prefix="/api/v1/tax", tags=["taxation"])

@router.post("/imports", status_code=201)
async def upload_import(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    content = await file.read(imports.MAX_IMPORT_FILE_BYTES + 1) if hasattr(imports, "MAX_IMPORT_FILE_BYTES") else await file.read()
    
    return imports.upload(file.filename, content, file.content_type, current_user, db)

@router.post("/imports/{batch_id}/preview")
def preview_import(batch_id: UUID, options: ImportPreviewOptions, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    return imports.preview(batch_id, options, current_user, db)

@router.post("/imports/{batch_id}/validate")
def validate_import(batch_id: UUID, options: ImportPreviewOptions, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    return imports.validate_batch(batch_id, options, current_user, db)

@router.post("/imports/{batch_id}/execute")
def execute_import(batch_id: UUID, options: ImportPreviewOptions, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    return imports.execute(batch_id, options, current_user, db)

@router.get("/import-mappings")
def list_import_mappings(db: Session = Depends(get_db), current_user: User = Depends(require_role())):
    return imports.list_mappings(current_user, db)

@router.post("/import-mappings", status_code=201)
def create_import_mapping(data: ImportMappingCreate, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    return imports.create_mapping(data, current_user, db)

@router.get("/import-mappings/{mapping_id}")
def get_import_mapping(mapping_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require_role())):
    return imports.get_mapping(mapping_id, current_user, db)

@router.patch("/import-mappings/{mapping_id}")
def update_import_mapping(mapping_id: UUID, data: ImportMappingUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    return imports.update_mapping(mapping_id, data, current_user, db)

@router.delete("/import-mappings/{mapping_id}", status_code=204)
def delete_import_mapping(mapping_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    imports.delete_mapping(mapping_id, current_user, db)

@router.post("/import-batches", status_code=201)
def create_import_batch(data: ImportBatchCreate, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    return fiscal_documents.create_import_batch(data, current_user, db)

@router.post("/documents", response_model=FiscalDocumentResponse, status_code=201)
def create_document(data: FiscalDocumentCreate, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    return fiscal_documents.create_document(data, current_user, db)

@router.get("/documents", response_model=list[FiscalDocumentResponse])
def list_documents(start_date: date | None = Query(default=None), end_date: date | None = Query(default=None), db: Session = Depends(get_db), current_user: User = Depends(require_role())):
    if start_date and end_date and end_date < start_date:
        from app.utils.exceptions import AppError
        raise AppError(status_code=422, message="end_date must be on or after start_date")
    
    return fiscal_documents.list_documents(current_user, db, start_date=start_date, end_date=end_date)

@router.get("/documents/{document_id}", response_model=FiscalDocumentResponse)
def get_document(document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require_role())):
    return fiscal_documents.get_document(document_id, current_user, db)

@router.patch("/documents/{document_id}", response_model=FiscalDocumentResponse)
def update_document(document_id: UUID, data: FiscalDocumentUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    return fiscal_documents.update_document(document_id, data, current_user, db)

@router.post("/calculate", response_model=TaxCalculationResponse)
def calculate(data: TaxCalculationRequest, db: Session = Depends(get_db), current_user: User = Depends(require_role())):
    return service.calculate_tax(current_user, db, data)

@router.post("/period/calculate", response_model=TaxPeriodCalculationResponse)
def calculate_period(data: TaxPeriodCalculationRequest, db: Session = Depends(get_db), current_user: User = Depends(require_role())):
    return tax_period.calculate_period(current_user, db, start_date=data.start_date, end_date=data.end_date, prior_carry_forward=data.prior_carry_forward, include_details=data.include_details)

@router.get("/profile")
def get_profile(db: Session = Depends(get_db), current_user: User = Depends(require_role())):
    return service.get_tax_profile(current_user, db)

@router.put("/profile")
def put_profile(data: TaxProfileInput, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    return service.put_tax_profile(data, current_user, db)

@router.post("/profile/validate")
def validate_profile(data: TaxProfileInput, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    return service.validate_tax_profile(data, current_user, db)

@router.get("/rules")
def get_rules(db: Session = Depends(get_db), current_user: User = Depends(require_role())):
    return service.list_tax_rules(current_user, db)

@router.post("/rules", status_code=201)
def post_rule(data: TaxRuleInput, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    return service.create_tax_rule(data, current_user, db)