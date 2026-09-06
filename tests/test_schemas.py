import pytest
from pydantic import ValidationError
from app.schemas.inventory import (
    InventoryMovementCreate,
    ProductCreate,
    SupplierCreate,
    SupplierUpdate,
)
from app.schemas.users import EmailRequest, PasswordReset, PasswordSet, UserLogin

def test_user_login_schema():
    data = UserLogin(
        email = "user@test.com",
        password = "Password123!",
    )

    assert data.email == "user@test.com"
    assert data.password == "Password123!"

def test_user_login_invalid_email():
    with pytest.raises(ValidationError):
        UserLogin(
            email = "correo_invalido",
            password = "Password123!",
        )

def test_email_request():
    data = EmailRequest(
        email = "user@test.com",
    )

    assert data.email == "user@test.com"

def test_email_request_invalid():
    with pytest.raises(ValidationError):
        EmailRequest(
            email = "abc",
        )

def test_password_set():
    data = PasswordSet(
        token = "abc123",
        new_password = "Password123!",
    )

    assert data.token == "abc123"

def test_password_reset():
    data = PasswordReset(
        token = "abc123",
        new_password = "Password123!",
    )

    assert data.token == "abc123"

def test_supplier_create_rejects_an_invalid_email():
    with pytest.raises(ValidationError):
        SupplierCreate(
            nombre = "Acme",
            correo = "not-an-email",
        )

def test_supplier_update_rejects_an_invalid_email():
    with pytest.raises(ValidationError):
        SupplierUpdate(
            correo = "not-an-email",
        )

def test_supplier_create_accepts_a_valid_email():
    data = SupplierCreate(
        nombre = "Acme",
        correo = "acme@example.com",
    )

    assert data.correo == "acme@example.com"

# ─── blank names and codes ────────────────────────────────────────────────────

def test_supplier_name_rejects_whitespace_only():
    with pytest.raises(ValidationError):
        SupplierCreate(
            nombre = "   ",
        )

def test_product_sku_rejects_whitespace_only():
    with pytest.raises(ValidationError):
        ProductCreate(
            sku = "  ",
            nombre = "Producto",
        )

def test_product_name_rejects_whitespace_only():
    with pytest.raises(ValidationError):
        ProductCreate(
            sku = "SKU-1",
            nombre = "\t \n",
        )

def test_product_unit_rejects_whitespace_only():
    with pytest.raises(ValidationError):
        ProductCreate(
            sku = "SKU-1",
            nombre = "Producto",
            unidad_medida = " ",
        )

def test_supplier_update_rejects_a_blank_name():
    with pytest.raises(ValidationError):
        SupplierUpdate(
            nombre = "  ",
        )

def test_surrounding_whitespace_is_trimmed_not_rejected():
    data = ProductCreate(
        sku = "  SKU-1  ",
        nombre = "  Producto  ",
    )

    assert data.sku == "SKU-1"
    assert data.nombre == "Producto"

def test_blank_optional_text_becomes_null():
    data = ProductCreate(
        sku = "SKU-1",
        nombre = "Producto",
        descripcion = "   ",
    )

    assert data.descripcion is None

def test_blank_optional_email_becomes_null():
    data = SupplierCreate(
        nombre = "Acme",
        correo = "   ",
    )

    assert data.correo is None

def test_movement_reason_is_trimmed():
    data = InventoryMovementCreate(
        producto_id = "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        tipo_movimiento = "entrada_manual",
        cantidad = "1.00",
        motivo = "  ajuste  ",
    )

    assert data.motivo == "ajuste"

def test_blank_movement_reason_becomes_null():
    data = InventoryMovementCreate(
        producto_id = "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        tipo_movimiento = "entrada_manual",
        cantidad = "1.00",
        motivo = "   ",
    )

    assert data.motivo is None
