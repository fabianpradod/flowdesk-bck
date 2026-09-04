# Flowdesk Backend

API REST construida con FastAPI para el sistema de gestión de inventario Flowdesk.

## URL de Producción

Base URL: `http://3.235.13.20`
Documentación: `http://3.235.13.20/docs`

## Estructura de Branches

- `main` — producción, no se toca directamente
- Desarrollo se hace en branches separados y se mergea a `main` cuando esté listo

## Variables de Entorno

Copiar `.env.example` como `.env` y completar los valores localmente. `.env` está
ignorado por Git y no debe enviarse por chat, correo ni incluirse en imágenes Docker.
En producción, guardar los secretos en el administrador de secretos de la plataforma
y rotarlos cuando una persona deje el equipo o se sospeche una exposición.

`docker-compose.yml` toma `DB_USERNAME`, `DB_PASSWORD` y `DB_DATABASE` desde
`.env`; no contiene credenciales predeterminadas y PostgreSQL no publica su puerto
fuera de la red interna de Compose. El servicio API fuerza `DB_SERVER=db` dentro de
Compose. Cambiar `DB_PASSWORD` no actualiza automáticamente un volumen PostgreSQL
ya inicializado: primero debe rotarse la contraseña del rol en PostgreSQL y después
actualizar el secreto.
Toda contraseña que haya aparecido previamente en el repositorio o en su historial
debe considerarse expuesta: hay que crear una nueva contraseña aleatoria para el rol
de PostgreSQL y actualizar el secreto desplegado; quitarla del Compose no sustituye
esa rotación.

## Opciones para el Equipo de Frontend

**Opción 1 — Usar la API de producción (recomendado)**
No necesitan correr nada localmente. Solo apunten su frontend a `http://3.235.13.20`.

**Opción 2 — Correr el backend localmente**
1. Instalar PostgreSQL localmente
2. Crear usuario `flowdesk` y base de datos `flowdesk`
3. Copiar `.env.example` a `.env` y llenar los valores
4. Cambiar `DB_SERVER=localhost` en el `.env` (el valor `db` es solo para producción)
5. Instalar dependencias: `pip install -r requirements.txt`
6. Correr: `uvicorn main:app --reload`

### Análisis inteligente — `/api/v1/ai`

El endpoint autenticado `POST /analysis` utiliza la API compatible con OpenAI de
Z.AI. Crear una clave en [la consola de Z.AI](https://z.ai/manage-apikey/apikey-list)
y configurar:

```env
ZAI_API_KEY=
ZAI_MODEL=glm-5.3-flash
ZAI_BASE_URL=https://api.z.ai/api/paas/v4
ZAI_TIMEOUT_SECONDS=30
```

`glm-5.3-flash` es una opción gratuita publicada por Z.AI; los límites y precios
pueden cambiar, por lo que deben comprobarse en su consola. Si no se configura
`ZAI_API_KEY`, el endpoint responde `503` sin impedir el arranque del resto de la
API. Nunca se registra ni se devuelve la clave.

El body acepta `scope=inventory|sales|catalog|business`, `period`, `start_date`,
`end_date`, `product_id`, `supplier_id`, `client_id`, `customer_type` y una
`question` opcional. Solo se envían métricas agregadas del tenant autenticado; no se
envían correos, nombres de usuarios, credenciales ni el nombre del esquema. La
respuesta siempre se valida con la estructura `summary`, `insights` y
`recommendations`. Z.AI es un tercero: antes de usar datos reales se deben revisar
sus términos, retención y tratamiento de datos vigentes.

Respuestas operativas: `400/422` para filtros inválidos, `401/403` para problemas de
acceso, `502` para una respuesta inválida del proveedor y `503` para clave ausente,
credenciales inválidas, rate limit o indisponibilidad temporal.

La integración externa no se ejecuta durante la suite normal. Para comprobar una
llamada real con la clave del `.env`, ejecutar explícitamente:

```powershell
$env:RUN_ZAI_INTEGRATION_TEST="1"
python -m pytest tests/test_zai.py -k live -v
```

## Endpoints

Documentación interactiva completa en `/docs`.

### Analítica — `/api/v1/analytics`

| Método | Path | Filtros principales |
|---|---|---|
| GET | `/sales/metrics` | `period`, `customer_type`, `client_id`, `start_date`, `end_date` |
| GET | `/sales/trend` | Los anteriores y `window=day|week|month` |
| GET | `/sales/top-products` | Los anteriores, `supplier_id`, `product_id`, `limit` |
| GET | `/inventory/risk-distribution` | `period`, `supplier_id`, `start_date`, `end_date` |
| GET | `/catalog/product-creation-trend` | `period`, `window`, `supplier_id`, `active_only`, fechas |

Las métricas y tendencias consideran únicamente ventas en estado `completada`,
`confirmada`, `finalizada` o `pagada`. La distribución de riesgo considera
productos activos y la demanda registrada mediante movimientos `salida_venta`.
El top de productos usa `detalle_venta`, por lo que representa ventas confirmadas y
no simples salidas de inventario. La tendencia de catálogo usa `producto.created_at`.

### Analítica de inventario — `/api/v1/inventory`

| Método | Path | Filtros principales |
|---|---|---|
| GET | `/analytics/monthly` | `period`, `product_id`, `start_date`, `end_date` |
| GET | `/analytics/trend` | Los anteriores y `window=day|week|month` |
| GET | `/analytics/products` | `period`, `sort_by`, `limit`, fechas |
| GET | `/metrics` | `period`, `product_id`, fechas |
| GET | `/history` | `limit`, `product_id`, `movement_type` |

### Auth — `/api/v1/auth`

| Método | Path | Rol |
|---|---|---|
| POST | `/register` | público |
| POST | `/login` | público |
| POST | `/password/set` | token `set_password` |
| POST | `/password/forgot` | público |
| POST | `/password/reset` | token `reset_password` |
| POST | `/invitations/resend` | admin+ |
| GET/POST | `/employees` | admin+ |

### Proveedores — `/api/v1/inventory/suppliers`

| Método | Path | Rol | Notas |
|---|---|---|---|
| GET | `` | cualquiera | Filtros `?search=` (nombre, parcial) y `?is_active=` |
| POST | `` | manager+ | El nombre no puede repetir el de otro proveedor activo |
| GET | `/{supplier_id}` | cualquiera | 404 si no existe |
| PUT | `/{supplier_id}` | manager+ | Solo se modifican los campos enviados |
| PATCH | `/{supplier_id}/status` | admin+ | Body `{"is_active": bool}` |
| DELETE | `/{supplier_id}` | admin+ | Soft delete — 204, marca `is_active=false` |

Un proveedor no puede desactivarse ni eliminarse mientras tenga productos activos
asociados; en ese caso la API responde 400 `Supplier still has active products`.
El campo `correo` se valida como email al crear y actualizar.

## Stack

- FastAPI
- PostgreSQL
- SQLAlchemy
- Docker + Docker Compose
- AWS EC2
