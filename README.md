# Flowdesk Backend

API REST multi-tenant construida con FastAPI, PostgreSQL y SQLAlchemy para
inventario, usuarios, clientes y tareas.

## Inicio rápido local

Requisitos: Python 3.11+, PostgreSQL 16 y un entorno virtual.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Complete los valores obligatorios de `.env`, cree la base configurada y ejecute:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

La documentación interactiva queda en `http://localhost:8000/docs`. Los probes
`GET /health` y `GET /ready` permiten comprobar el proceso y la conexión a la
base de datos, respectivamente.

## Inicio con Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

El contenedor publica la API en el puerto 80. La primera ejecución crea las
tablas globales y cada empresa recibe un esquema PostgreSQL independiente.

## Variables de entorno

| Variable | Obligatoria | Uso |
|---|---|---|
| `DB_SERVER` | sí | Host de PostgreSQL (`localhost` local, `db` en Compose) |
| `DB_DATABASE` | sí | Nombre de la base |
| `DB_USERNAME` | sí | Usuario de la base |
| `DB_PASSWORD` | sí | Contraseña de la base |
| `DB_PORT` | no | Puerto, 5432 por defecto |
| `SECRET_KEY` | sí | Firma JWT; use un valor aleatorio largo |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no | Duración de access tokens |
| `SUPERADMIN_EMAIL` | sí | Correo del superadministrador inicial |
| `SUPERADMIN_USERNAME` | sí | Usuario del superadministrador inicial |
| `SUPERADMIN_PASSWORD` | sí | Contraseña inicial del superadministrador |
| `SMTP_USERNAME` | sí | Cuenta de envío de invitaciones y recuperación |
| `SMTP_PASSWORD` | sí | Credencial SMTP |
| `FRONTEND_URL` | sí | Origen CORS y base de enlaces enviados por correo |
| `DEMO_SEED_ENABLED` | no | Habilita usuarios demo; desactivado por defecto |
| `DEMO_USER_PASSWORD` | si activa demo | Contraseña de usuarios demo |

No suba `.env` al repositorio. `.env.example` solo contiene valores de ejemplo.

## Contrato consumido por frontend

La especificación completa está en `/docs`. Estos son los grupos principales:

- `/api/v1/auth`: registro, inicio de sesión, invitaciones y contraseñas.
- `/api/v1/companies`: listado de empresas para superadministración.
- `/api/v1/users` y `/api/v1/roles`: administración de empleados y roles.
- `/api/v1/inventory`: productos, proveedores, movimientos y analítica.
- `/api/v1/commercial`: clientes.
- `/api/v1/tasks`: tareas personales del usuario autenticado.

### Tareas

Los estados válidos son `pendiente`, `en_progreso`, `completada` y `cancelada`;
las prioridades son `baja`, `media`, `alta` y `urgente`. Todas las consultas se
restringen al usuario y al esquema tenant autenticados.

| Método | Path | Descripción |
|---|---|---|
| GET | `/api/v1/tasks` | Lista y filtra por `estado`, `prioridad` o `search` |
| POST | `/api/v1/tasks` | Crea una tarea pendiente |
| GET | `/api/v1/tasks/{task_id}` | Obtiene una tarea propia |
| PUT | `/api/v1/tasks/{task_id}` | Actualiza los campos enviados |
| PATCH | `/api/v1/tasks/{task_id}/status` | Cambia el estado |
| DELETE | `/api/v1/tasks/{task_id}` | Elimina una tarea propia |

## Pruebas

```bash
pytest -q
```

Las pruebas no requieren un PostgreSQL real: reemplazan la inicialización y las
dependencias de persistencia cuando corresponde.
