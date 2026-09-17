from uuid import uuid4
from app.models.tenant.commercial import Venta
from app.models.tenant.registry import build_tenant_metadata

def test_sale_accepts_registered_client_id():
    client_id = uuid4()
    sale = Venta(cliente_id=client_id)

    assert sale.cliente_id == client_id

def test_sale_client_foreign_key_targets_client_in_same_tenant():
    schema_name = "tenant_client_sale_test"
    metadata = build_tenant_metadata(schema_name)
    sales = metadata.tables[f"{schema_name}.venta"]
    foreign_key = next(iter(sales.c.cliente_id.foreign_keys))

    assert foreign_key.target_fullname == f"{schema_name}.cliente.id"