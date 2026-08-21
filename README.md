# Flowdesk Backend

API REST construida con FastAPI para el sistema de gestión de inventario Flowdesk.

## URL de Producción

Base URL: `http://3.235.13.20`
Documentación: `http://3.235.13.20/docs`

## Estructura de Branches

- `main` — producción, no se toca directamente
- Desarrollo se hace en branches separados y se mergea a `main` cuando esté listo

## Variables de Entorno

El archivo `.env` se comparte por privado (nunca se sube al repo). Copiar `.env.example` y renombrarlo a `.env` con los valores que les comparta el líder del proyecto.

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

## Endpoints

Documentación interactiva completa en `/docs`.

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

### Reportes — `/api/v1/reports`

Todos los endpoints de reportes requieren rol admin o superior.

| Método | Path | Notas |
|---|---|---|
| GET | `/history` | Historial de reportes generados. `?limit=` entre 1 y 100 (default 20) |
| GET | `/inventario` | Stock actual. Filtros `?product_id=`, `?is_active=`, `?only_low_stock=` |
| GET | `/movimientos` | Movimientos del período. Filtros `?period=`, `?start_date=`, `?end_date=`, `?product_id=`, `?movement_type=` |
| GET | `/alertas` | Alertas del período. Filtros `?period=`, `?start_date=`, `?end_date=`, `?open_only=` |

Los tres reportes aceptan `?format=csv` (default) o `?format=pdf` y responden con el
archivo como descarga (`Content-Disposition: attachment`), no con JSON.

`period` acepta `7d`, `30d` (default), `90d`, `6m`, `12m`, `ytd` o `custom`; con `custom` hay
que enviar `start_date` y `end_date`, de lo contrario la API responde 400.

Cada generación queda registrada en la tabla `reporte` del esquema de la empresa y se
consulta con `GET /history`. El archivo no se almacena en el servidor — se transmite
directamente al cliente, por lo que `ruta_archivo` siempre viene en `null`.

El CSV se genera con BOM UTF-8 para que Excel muestre bien los acentos, y las celdas que
empiezan con `=`, `+`, `-` o `@` se escapan para evitar inyección de fórmulas.

## Stack

- FastAPI
- PostgreSQL
- SQLAlchemy
- Docker + Docker Compose
- AWS EC2