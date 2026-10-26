# Sprint 10: movimientos paginados y rendimiento

Fecha: 26 de octubre de 2026. SCRUM-793–801; base `ed8138b`.

## Revisión y decisión

El repositorio ya tenía `tests/load/flowdesk_load.js`, el generador de datos y el
resumidor de CSV, además de pool configurado y admisión limitada de solicitudes.
No se encontró un reporte k6 histórico versionado. Se ejecutó una nueva línea
base local sobre el commit base, antes de aplicar los cambios de este PR.

El endpoint sin límite de movimientos fue el mayor p95 a 100 VUs: 1178 ms. Cada
empresa tenía 20 000 movimientos; devolverlos completos crea coste de consulta,
serialización y transferencia que un índice no elimina. Por eso se agrega una
ruta paginada y se preserva el contrato anterior para los consumidores existentes.

## SCRUM-795/796: contrato y optimización

```text
GET /api/v1/inventory/movements/page?limit=100&product_id=<uuid>&cursor=<next_cursor>
```

Respuesta `{items, next_cursor}`. Misma autorización y empresa que la lectura
existente: cualquier usuario autenticado de una empresa activa, sin acceso a
otros tenants. Límite 1–500; cursor de hasta 1024 caracteres; `product_id` opcional.

Orden descendente estable por `(fecha, id)`; `limit + 1` permite saber si hay más
sin COUNT ni OFFSET. El cursor valida empresa, recurso y producto. No contiene
un nombre de esquema ni funciona como credencial. La consulta siempre resuelve
el esquema desde el usuario autenticado. Fechas iguales se desempatan con UUID;
una inserción más reciente no duplica filas al continuar desde el cursor.

Índices: `(fecha, id)` y `(producto_id, fecha, id)`. Se crean en tenants nuevos y
existentes mediante bootstrap idempotente. Los índices no son concurrentes:
planificar el despliegue en ventana de mantenimiento según tamaño de cada tenant.
No se actualizan las fechas de movimientos existentes como parte de la migración.

**Compatibilidad:** `GET /movements` conserva su lista completa. El frontend debe
adoptar `/movements/page` y consumir `next_cursor` para obtener el beneficio. No
se cambia a escondidas una lista completa por solo sus primeras 100 filas. No se
ha modificado el repositorio del frontend en este PR.

## SCRUM-797: pool PostgreSQL

La base ya usa QueuePool con `pool_pre_ping`, size=20, max_overflow=20,
timeout=30 s y recycle=3600 s por proceso; `PoolAdmissionMiddleware` limita a
40 solicitudes dentro de la aplicación y deja `/health` fuera de esa espera.
No se amplía el pool a ciegas para compensar consultas que devuelven miles de filas.

El presupuesto máximo de conexiones crece como
`workers × (DB_POOL_SIZE + DB_MAX_OVERFLOW)`, más migración/operación/otros
consumidores. Dos workers con defaults pueden usar 80 conexiones y tres, 120.
Dimensionar contra `max_connections`, memoria y carga reales antes de configurar
replicación. La prueba usó PostgreSQL local en Docker; no valida el presupuesto de
la instancia de producción ni obliga a aumentar los defaults.

## SCRUM-798: evaluación multi-worker

Se compara el mismo workload paginado con uno y dos workers sobre dos copias
PostgreSQL del mismo snapshot. Uvicorn puede iniciar varios workers; no se agrega
Gunicorn ni se cambia la cantidad de workers de producción.

**Se conserva un worker por defecto.** `chat_admission.py` mantiene sus slots y
usuarios activos en memoria del proceso, y el rate limit de recuperación de
contraseña también es local. Con dos procesos dejan de ser límites globales.
Antes de habilitar varios workers deben coordinarse mediante un mecanismo
compartido y verificarse con concurrencia entre procesos.

Además, el `init_db()` actual corre al importar la aplicación: varias réplicas
pueden competir durante la creación/migración. En las mediciones se inicializó y
sembró la base una sola vez; `scripts/benchmark_app.py` omite únicamente esa
inicialización y exige un host PostgreSQL explícito de loopback y una base de
pruebas `flowdesk_*`. Ese módulo no es el entrypoint de despliegue.

Referencia de funcionamiento y coste por proceso:
[FastAPI: Server Workers](https://fastapi.tiangolo.com/deployment/server-workers/).

## SCRUM-799/800: metodología y resultados

- API real con Uvicorn 0.38.0, Python 3.14.3, PostgreSQL 16 en Docker y k6 oficial
  (imagen usada: `grafana/k6@sha256:3e4186aea62e11a45560bfc51e19eeafe82fc07ce069c78aff44b7ff893d9a5e`).
- Dos empresas sintéticas: por empresa 1000 productos, 50 proveedores, 300 clientes,
  20 000 movimientos y 5000 ventas. Semilla aleatoria 2026. No datos de producción,
  correos reales ni llamadas a Z.AI.
- Workload mixto existente: veinte grupos de endpoints, mayormente lecturas y 3 %
  movimientos nuevos. Cada nivel 25/50/100 VUs se mantiene 30 s, con rampas entre
  niveles; corrida de 145 s más setup/graceful stop.
- El resumen cuenta solo los tramos estables; los percentiles se calculan a partir
  de muestras CSV. La selección de endpoints es aleatoria, no exactamente la misma
  secuencia entre corridas. Los errores reportados son HTTP; no sustituyen todas
  las aserciones de integridad de los tests.
- La base before y after-legacy se sembró por separado con la misma escala y semilla
  (UUIDs/fechas no idénticos). Las corridas paginadas de uno/dos workers parten de
  clones del mismo snapshot para comparar esa variable.
- No se mezclan dos cargas simultáneas. Las mediciones locales no son un benchmark
  de hardware dedicado; pueden variar por scheduler/caché y actividad de desarrollo.
  Se conserva el resultado observado, incluso cuando empeora.

### Mismo contrato legacy, un worker

| VUs | p95 base ms | p95 cambios ms | Cambio | Errores HTTP base/cambios |
|---|---:|---:|---:|---:|
| 25 | 319.7 | 366.7 | +15 % | 0 % / 0 % |
| 50 | 587.4 | 617.6 | +5 % | 0 % / 0 % |
| 100 | 1042.9 | 1219.1 | +17 % | 0 % / 0 % |

La incorporación de auditoría/índices **no demuestra una mejora del contrato
legacy**: el p95 observado aumentó. La auditoría añade una escritura a movimientos
(3 % del workload) y los índices no eliminan la respuesta completa. No se atribuye
todo el aumento a una causa sin réplicas controladas; es un riesgo de rendimiento
visible para revisión. Ver `before.json` y `after-legacy.json` por endpoint.

### Variante paginada y cantidad de workers

| VUs | p95 cursor / 1 worker ms | req/s | p95 cursor / 2 workers ms | req/s | Errores HTTP |
|---|---:|---:|---:|---:|---:|
| 25 | 167.7 | 234.3 | 96.6 | 457.6 | 0 % en ambas |
| 50 | 296.5 | 241.1 | 199.1 | 410.4 | 0 % en ambas |
| 100 | 540.0 | 248.7 | 354.9 | 413.8 | 0 % en ambas |

Resúmenes: `cursor-one.json` y `cursor-two.json`. En esta máquina, el workload
con páginas reduce el volumen y mejora el p95 observado; dos procesos aportan
capacidad adicional. Aun así, **a 100 VUs no se alcanza el umbral de 200 ms**.
Las cuatro corridas salen con código k6 99 por `http_req_duration`; no hay errores
HTTP. La validación de carga no se declara completamente verde.

El primer page SQL usa `ix_movimiento_fecha_id` y LIMIT, con 101 filas examinadas
y aproximadamente 0.04 ms de ejecución en el plan local con caché. Ese tiempo es
solo SQL, no la latencia HTTP; no demuestra por sí solo el p95 de producción.
Los tests verifican la continuación por cursor y las fechas iguales por separado.

Se recomienda adoptar paginación y medir con consumidores reales. **No se activa
multi-worker en producción** mientras los límites de chat/reset sean locales y
no exista una etapa única de migración.

Los cambios de payload de la variante cursor se muestran por separado: devolver
100 filas no es el mismo trabajo que devolver toda la historia. No se interpreta
su diferencia como una mejora idéntica de la ruta antigua. El umbral original
`p(95)<200 ms` se conserva; el resumen y el código de salida deben mostrar si se
cumplió. No se relaja el umbral para conseguir una corrida verde.

### Evidencia y reproducción

Los JSON de este directorio contienen resúmenes y una verificación HTTP/PostgreSQL
con 14 checks más un plan EXPLAIN. El plan del primer page usa el índice de fecha
con LIMIT. El CSV completo de trabajo está en `/tmp/flowdesk-sprint10` durante esta
sesión y se regenera con los comandos siguientes; no se versionan fixtures con
credenciales/tokens ni archivos de varios MB por corrida.

1. Levantar un PostgreSQL descartable accesible por loopback y crear una base
   `flowdesk_*` vacía. Exportar DB_SERVER/DB_PORT/DB_DATABASE/DB_USERNAME/DB_PASSWORD
   y una SECRET_KEY válida exclusivamente de pruebas.
2. Generar datos con `tests/load/seed_load_data.py --dsn <DSN local> --out <fixture>
   --companies 2 --scale 1`. El script no admite hosts remotos. Guardar un snapshot
   antes de medir y clonarlo para comparar workers sin cambiar los datos iniciales.
3. Exportar `BENCH_SOURCE` al checkout a evaluar y arrancar desde este repositorio:

```bash
.venv/bin/python -m uvicorn benchmark_app:app --app-dir scripts \
  --host 0.0.0.0 --port 18813 --workers 1 --no-access-log
```

4. Ejecutar k6 con montajes a los scripts y al directorio temporal de fixture/CSV:

```bash
k6 run -e FIXTURE=/abs/fixture.json -e BASE_URL=http://127.0.0.1:18813 \
  --out csv=run.csv tests/load/flowdesk_load.js
```

Agregar `-e MOVEMENT_PAGINATION=cursor` para las dos lecturas de movimientos
paginadas. El resto del escenario, niveles, pesos y umbrales no cambia. Para la
comparación multi-worker repetir desde el snapshot con `--workers 2`.

```bash
.venv/bin/python tests/load/summarize_k6.py summary run.csv --json run.json
.venv/bin/python tests/load/summarize_k6.py compare before.json after.json --stage 100
.venv/bin/python scripts/verify_sprint10.py --base-url http://127.0.0.1:18813 \
  --fixture /abs/fixture.json --dsn '<DSN local>' --out verification.json
```

El verificador rechaza hosts remotos y usa solo usuarios del fixture sintético.
Detener las APIs y retirar el contenedor descartable al terminar.

## Pendientes de despliegue

Migración una sola vez, revisión de lock/memoria/pool, adopción del cursor en el
frontend, repetir mediciones con dataset y hardware representativos, y coordinar
límites compartidos antes de habilitar multi-worker. Los resultados locales no
certifican el p95 de producción ni cubren proxy/TLS o servicios externos de IA.
No se cierran tickets ni se publica un despliegue desde este trabajo.
