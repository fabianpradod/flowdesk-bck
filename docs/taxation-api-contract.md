# Contrato de API tributaria para frontend

Este documento describe el contrato HTTP actualmente expuesto por FlowDesk para administrar configuración tributaria, simular cálculos, importar documentos fiscales, calcular períodos y descargar el reporte tributario.

El tenant se obtiene exclusivamente del usuario autenticado. El cliente no debe enviar `tenant_id`, `company_id` ni `schema_name` para seleccionar el contexto.

## Convenciones

- Autenticación: `Authorization: Bearer <token>` según el mecanismo general de FlowDesk.
- Las rutas de lectura requieren usuario autenticado. Las operaciones administrativas requieren rol `admin` (o `superadmin` según la política jerárquica actual).
- Las fechas se envían como `YYYY-MM-DD`.
- Los importes `Decimal` se envían y reciben como strings JSON, por ejemplo `"100.00"`. No convertirlos a `float`.
- Los errores tienen la forma `{ "message": string, "code": string, "errors": [] }`.
- Errores de validación de request usan HTTP `422` y código `validation_error`; autenticación/autorización usa `401`/`403`; recursos inexistentes usan `404`; conflictos de versiones usan `409` cuando corresponde.

## Configuración tributaria

### `GET /api/v1/tax/profile`

Devuelve el contenedor tenant-scoped de perfiles, incluyendo versiones, vigencia, impuestos y reglas. La respuesta actual es un objeto con `profiles`.

### `PUT /api/v1/tax/profile`

Guarda una versión de perfil. Requiere `admin`. El request usa `TaxProfileInput`:

```json
{
  "name": "Perfil configurable",
  "jurisdiction": "TEST",
  "regime": "CONFIGURABLE",
  "default_currency": "USD",
  "effective_from": "2026-01-01",
  "effective_until": null,
  "version_id": "profile-v1",
  "precision": 2,
  "rounding": "HALF_UP",
  "taxes": [],
  "rules": [],
  "metadata": {}
}
```

Las versiones históricas no deben editarse destructivamente. Para un cambio futuro se crea una nueva versión con una fecha de vigencia posterior. Los solapamientos y fechas inválidas producen error.

### `POST /api/v1/tax/profile/validate`

Valida un perfil sin persistirlo. Devuelve `valid`, `errors`, `warnings` e `information`. Es el paso recomendado antes de `PUT`.

### `GET /api/v1/tax/rules`

Lista las reglas de los perfiles del tenant autenticado.

### `POST /api/v1/tax/rules`

Crea una regla declarativa dentro del perfil vigente más reciente. Requiere `admin`. El request acepta `scope`, `condition`, `calculation`, `result`, `tax_code`, `priority`, `effective_from`, `effective_until`, `version_id` y `metadata`.

Las condiciones son datos declarativos; no contienen Python ejecutable. Los scopes y resultados deben ser compatibles con el `TaxEngine` existente.

## Simulación

### `POST /api/v1/tax/calculate`

Calcula operaciones en memoria usando el perfil resuelto por `as_of` o el `profile_version` indicado. No crea `FiscalDocument`, `TaxComponent`, `ImportBatch` ni modifica ventas.

```json
{
  "as_of": "2026-01-15",
  "profile_version": "profile-v1",
  "tax_debit": "100.00",
  "prior_carry_forward": "0.00",
  "operations": [
    {
      "tax_amount": "40.00",
      "taxable_base": "400.00",
      "tax_category": "TAXABLE",
      "tax_code": "TAX_A",
      "document_direction": "INPUT",
      "operation_date": "2026-01-15"
    }
  ]
}
```

La respuesta contiene `tax_debit`, `tax_credit`, `net_tax`, `tax_payable`, `carry_forward`, `withholding_tax` y `details`. Una operación no calculable se representa dentro del resultado/detalle según la clasificación, mientras una entrada inválida o una configuración inexistente produce error HTTP.

## Cálculo periódico

### `POST /api/v1/tax/period/calculate`

Calcula el período usando ventas históricas y documentos fiscales persistidos del tenant.

```json
{
  "start_date": "2026-01-01",
  "end_date": "2026-01-31",
  "prior_carry_forward": "0.00",
  "include_details": true
}
```

La respuesta incluye período, débito, crédito, retenciones, neto, importe a pagar, saldo a favor, moneda, conteos y detalles de trazabilidad.

## Importación fiscal

### Mappings

- `GET /api/v1/tax/import-mappings` — lista mappings visibles para el tenant.
- `POST /api/v1/tax/import-mappings` — crea un mapping; requiere `admin`.
- `GET /api/v1/tax/import-mappings/{mapping_id}` — consulta un mapping tenant-scoped.
- `PATCH /api/v1/tax/import-mappings/{mapping_id}` — modifica un mapping; requiere `admin`.
- `DELETE /api/v1/tax/import-mappings/{mapping_id}` — elimina un mapping; requiere `admin`.

El mapping contiene `source_type` (`CSV` o `XLSX`), columnas, locale, separadores, encoding, hoja, filas de encabezado y paths normalizados. Es configuración, no legislación.

### Flujo de archivo

1. `POST /api/v1/tax/imports` con multipart `file`.
2. `POST /api/v1/tax/imports/{id}/preview` con `mapping_id` u opciones de mapping.
3. `POST /api/v1/tax/imports/{id}/validate`.
4. `POST /api/v1/tax/imports/{id}/execute`.

Preview y validation devuelven headers, filas, muestras normalizadas, errores, warnings, columnas no mapeadas y candidatos duplicados. Preview no persiste documentos. Execute devuelve estado (`IMPORTED`, `PARTIAL` o `FAILED`), totales, filas fallidas, duplicados y warnings.

El límite técnico actual es 10 MiB y 10.000 filas. El archivo se conserva temporalmente en memoria durante el flujo; si expira, el endpoint responde `404` indicando que ya no está disponible.

También existe:

- `POST /api/v1/tax/import-batches` para crear un batch explícito con metadatos.

## Documentos fiscales

- `POST /api/v1/tax/documents` — crea un documento normalizado; requiere `admin`.
- `GET /api/v1/tax/documents` — lista documentos, con filtros opcionales `start_date` y `end_date`.
- `GET /api/v1/tax/documents/{id}` — consulta un documento y sus líneas/componentes.
- `PATCH /api/v1/tax/documents/{id}` — actualización controlada de estado/metadata; requiere `admin`.

Los importes, tasas, categorías y componentes almacenados son snapshots históricos. Cambiar el perfil no los recalcula automáticamente.

## Reportes y analytics

### `GET /api/v1/reports/tributario`

Requiere `admin`. Acepta `regime`, `period`, `start_date` y `end_date`, y devuelve un archivo XLSX mediante `Content-Disposition` y `Content-Length`. Los regímenes contractuales actuales incluyen `SMALL_TAXPAYER` y `GENERAL_VAT`.

### `GET /api/v1/analytics/sales/fiscal-debit`

Requiere `manager` o `admin` con autorización estricta. Acepta período y fechas, y devuelve el débito histórico de ventas.

## Seguridad y CORS

Las rutas usan el usuario autenticado para resolver el schema tenant. Un ID de otro tenant no habilita lectura, modificación ni cálculo cruzado. El CORS actual permite los orígenes locales `http://localhost:5173` y `http://localhost:3000`, además de `FRONTEND_URL` cuando está configurado; se permiten credenciales, métodos y headers necesarios para el frontend.

## Flujo recomendado de UI

```text
GET profile
  → POST profile/validate
  → PUT profile
  → POST calculate (simulación)
  → crear/reutilizar mapping
  → upload
  → preview
  → validate
  → execute
  → period/calculate
  → descargar reports/tributario
```

La API tributaria no presenta declaraciones fiscales oficiales, filing, conversión monetaria automática ni legislación específica de un país.

## Observaciones de contrato actual

Las respuestas de importación, profile y mappings son objetos dinámicos sin `response_model` dedicado; el frontend debe consumir los campos documentados y tolerar metadata adicional. Los errores mantienen una forma común y HTTP status distinguible, pero algunos errores internos de servicios todavía usan el código general `app_error` en lugar de códigos de dominio más granulares. Esta es una limitación de refinamiento del contrato, no una vía para seleccionar otro tenant ni para alterar el cálculo.