from app.models.tenant.commercial import Venta
from app.models.tenant.registry import build_tenant_metadata

def test_sale_client_is_optional_for_final_consumer():
    sale = Venta(cliente_id=None)

    assert sale.cliente_id is None
    assert Venta.__table__.c.cliente_id.nullable is True

def test_tenant_sale_schema_keeps_client_optional():
    metadata = build_tenant_metadata("tenant_consumer_test")
    sales = metadata.tables["tenant_consumer_test.venta"]

    assert sales.c.cliente_id.nullable is True