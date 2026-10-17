"""Compatibility boundary for the pre-existing sales tax configuration."""
from decimal import Decimal
from sqlalchemy import select

def resolve_legacy_sales_rate(db, configuration) -> Decimal:
    row = db.execute(select(configuration.c.tasa_impuesto).order_by(configuration.c.updated_at.desc(), configuration.c.created_at.desc()).limit(1)).mappings().first()
    
    return Decimal("0.00") if row is None else Decimal(str(row["tasa_impuesto"]))