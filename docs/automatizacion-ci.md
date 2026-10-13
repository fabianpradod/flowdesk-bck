# Tarea 5: CI y pruebas con PostgreSQL real

## Workflow

`.github/workflows/tests.yml` se activa con `push` y `pull_request` en cualquier rama. La ejecución manual queda disponible al incorporarlo a la rama predeterminada. Usa Python 3.11 y dos jobs independientes:

- `suite`: instala dependencias, ejecuta la regresión existente (`tests/test_sprint_regression.py`) y todas las pruebas en `tests/`, con cobertura y JUnit. Esta suite conserva sus simulaciones de base de datos, correo y proveedor AI.
- `postgres-integration`: levanta PostgreSQL 16 temporal, arranca `main:app` con Uvicorn, espera `/ready` y ejecuta las pruebas de `integration/` por HTTP real. No utiliza las fixtures de `tests/conftest.py` ni FakeDB.

El entorno usa credenciales públicas de prueba para una base desechable y datos demo sintéticos. No requiere secretos de producción. El job finaliza el proceso API, y GitHub elimina el contenedor al terminar el runner. Este workflow no despliega. El workflow previo `deploy.yml` sigue independiente: un CI rojo no bloquea automáticamente ese despliegue existente.

## Tres comprobaciones de integración reales

| Prueba | Componentes | Datos | Resultado esperado |
|---|---|---|---|
| `test_readiness_checks_real_postgres` | HTTP, router `/ready`, dependencia DB, PostgreSQL | Base inicializada y empresa demo | HTTP 200, estado `ready` y empresa persistida. |
| `test_persisted_user_login_and_protected_roles` | Login, bcrypt, usuario persistido, JWT, autorización y consulta de roles | Administrador demo activo | Login 200, token bearer, roles iguales a los de PostgreSQL y acceso anónimo 401. |
| `test_task_lifecycle_is_persisted_and_owned` | HTTP, JWT, servicio de tareas, tenant, SQLAlchemy y PostgreSQL | Administrador, empleado y título UUID único | Crear 201, fila persistida con dueño correcto, lectura 200, acceso del otro usuario 404, estado `completada` persistido y eliminación 204 sin fila residual. |

Estas comprobaciones permiten validar el entorno que CI prepara. El responsable de pruebas del equipo puede ampliar los casos de negocio sin cambiar el proceso de publicación de evidencia.

## Reproducción local

Requiere Python 3.11 y Docker activo:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/run_integration_local.py
```

El script usa un contenedor propio con nombre aleatorio, puertos disponibles y sin volumen persistente. Arranca la API con variables exclusivas de prueba y elimina su proceso y contenedor al finalizar. Los reportes quedan en `reports/`. Las pruebas en `integration/` se ejecutan explícitamente; `pytest` sin argumentos mantiene la selección histórica de `tests/`.

## Evidencias y límites

Cada job publica XML JUnit, logs y resúmenes Markdown/JSON con commit y URL de ejecución. La suite publica cobertura HTML/XML, y la integración publica el log de Uvicorn. `if: always()` conserva los artefactos incluso si falla una prueba. Retención: 90 días; descargar antes del vencimiento. `pipefail` mantiene el código de fallo de pytest cuando la salida pasa por `tee`.

Las pruebas externas de Z.AI no se habilitan porque necesitan credenciales y acceso a un servicio de terceros. Las pruebas omitidas de la suite original deben aparecer como omitidas, no como aprobadas. El workflow de integración comprueba persistencia y autenticación reales, pero no garantiza carga, concurrencia, entrega de email, disponibilidad de AI ni el recorrido completo del frontend en un navegador.

La demostración deliberada exitosa-fallida-corregida se realiza en `yehosuah/flowdesk-frt` con la prueba existente de descuentos; su guía está en `docs/automatizacion-ci.md` de ese repositorio.

## Referencias oficiales

- [GitHub Actions: eventos](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [GitHub Actions: artefactos](https://docs.github.com/en/actions/tutorials/store-and-share-data)
- [pytest: reportes JUnit](https://docs.pytest.org/en/stable/how-to/output.html)
