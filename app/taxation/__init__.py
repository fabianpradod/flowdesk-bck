"""Generic, tenant-configured tax domain and declarative calculation engine."""

from app.taxation.domain import (
    CalculationError,
    TaxCalculation,
    TaxDefinition,
    TaxProfile,
    TaxRule,
    TaxableOperation,
    TaxValidationError,
    TAX_RULE_SCOPES,
    WITHHOLDING_EFFECTS,
    validate_profile_versions,
    resolve_profile,
)
from app.taxation.engine import TaxEngine
from app.taxation.classifier import ClassificationResult, FiscalClassifier

__all__ = [
    "CalculationError", "TaxCalculation", "TaxDefinition", "TaxEngine",
    "TaxProfile", "TaxRule", "TaxValidationError", "TaxableOperation", "TAX_RULE_SCOPES", "WITHHOLDING_EFFECTS", "resolve_profile", "validate_profile_versions",
    "ClassificationResult", "FiscalClassifier",
]