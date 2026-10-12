# Rendimiento del backend bajo carga

Revisión de la gestión de conexiones y de las consultas del backend para mantener
tiempos de respuesta adecuados con alta concurrencia. Medido sobre `main` en
`f5fe052`, octubre de 2026.

## Antecedentes

El trabajo previo con k6 está en la rama `test/non-functional-tests`
(`load_test.js`, `stress_test.js` y `docs/reportes_pruebas/Volumen-K6.md`). Ambos
scripts llaman solo a `GET /health`, que no consulta la base de datos ni valida el
token, y el reporte no guarda la salida de k6. Por eso sus cifras (p95 cercano a
450 ms con 100 usuarios) no se pueden reproducir ni dicen nada sobre el pool de
conexiones o las consultas.

De ese trabajo se conservan los niveles de carga (25, 50 y 100 usuarios
virtuales), el objetivo (p95 menor a 200 ms y menos de 1 % de errores) y la
sospecha de que el pool de SQLAlchemy era un límite. La línea base de este
documento se midió de nuevo sobre endpoints que sí usan la base.

## Método

### Entorno

| Componente | Valor |
|---|---|
| Máquina | Apple M4, 10 núcleos, 16 GB |
| Base de datos | PostgreSQL 16.13 local y desechable, `max_connections = 100` (igual que la imagen `postgres:16` de Compose), con `pg_stat_statements` |
| API | Un proceso `uvicorn` con los mismos flags del `Dockerfile` |
| Versiones | Python 3.13.5 (la imagen usa 3.11), FastAPI 0.119.1, SQLAlchemy 2.0.43, uvicorn 0.38.0, k6 2.3.0 |

k6 y la API corren en la misma máquina, sin `.env`, sin la base real y sin
correo. Las cifras absolutas no son las de EC2: sirven para comparar antes y
después en las mismas condiciones.

### Datos

`tests/load/seed_load_data.py` llena una base vacía con dos empresas. Cada una
tiene 8 usuarios (1 admin, 2 manager, 5 employee), 50 proveedores, 1,000
productos, 2,000 cotizaciones de proveedor, 300 clientes, 20,000 movimientos de
inventario y 5,000 ventas (unas 15,000 líneas) repartidos en los últimos 12
meses, 100 alertas y 160 tareas. El script rechaza cualquier host que no sea
local. Cada corrida parte de la misma copia de la base.

### Escenario

`tests/load/flowdesk_load.js` inicia sesión una vez por usuario (un admin y dos
manager de cada empresa) y después cada usuario virtual repite solicitudes sin
pausas. Así, el número de usuarios virtuales es el número de solicitudes en
curso: 100 usuarios virtuales equivalen a muchos más usuarios reales, que
esperan entre una acción y otra.

La mezcla tiene 20 operaciones con peso fijo: 18 lecturas que consultan la base
(productos, proveedores, movimientos, alertas, historial, métricas, analítica de
inventario y de ventas, clientes, compras por cliente, detalle de venta, tareas),
un `POST /inventory/movements` y `GET /health` como control sin base de datos.

Las etapas son una rampa de 15 s y 30 s sostenidos en 25, 50 y 100 usuarios.
`tests/load/summarize_k6.py` calcula p50, p95 y p99 por etapa y por endpoint,
contando solo los periodos sostenidos.

### Cómo reproducir

```bash
createdb flowdesk_perf
python tests/load/seed_load_data.py \
    --dsn postgresql+psycopg2://postgres@127.0.0.1:5432/flowdesk_perf \
    --out /tmp/fixture.json
# API con DB_* apuntando a flowdesk_perf, un SECRET_KEY de prueba y SMTP vacío
uvicorn main:app --host 127.0.0.1 --port 8800 --proxy-headers --forwarded-allow-ips '*'
k6 run -e FIXTURE=/tmp/fixture.json -e BASE_URL=http://127.0.0.1:8800 \
    --out csv=run.csv tests/load/flowdesk_load.js
python tests/load/summarize_k6.py summary run.csv --json run.json
```

## Línea base en main

### Resultados globales

Dos corridas sobre `main`, con la misma base y el mismo script.

| Usuarios | Corrida | Solicitudes/s | p50 ms | p95 ms | p99 ms | Errores |
|---|---|---|---|---|---|---|
| 25 | 1 | 79 | 242 | 715 | 924 | 0 % |
| 25 | 2 | 79 | 269 | 629 | 877 | 0 % |
| 50 | 1 | 74 | 550 | 1,325 | 1,787 | 0 % |
| 50 | 2 | 71 | 608 | 1,339 | 1,782 | 0 % |
| 100 | 1 | 0 | | | | 1 solicitud completada en 30 s |
| 100 | 2 | 0 | | | | 4 solicitudes completadas en 30 s |

- El rendimiento no sube al pasar de 25 a 50 usuarios: el servidor ya está
  saturado con 25. Lo que crece es la espera.
- Con 100 usuarios la API se detiene por completo. Las corridas terminaron con 86
  y 87 solicitudes fallidas (1.1 %): errores 500 por
  `QueuePool limit of size 5 overflow 10 reached, connection timed out` (68 y 67
  en el log de la API) y solicitudes que k6 abandonó a los 60 s.
- La variación entre corridas en el p95 es de un 10 %.

### Latencia por endpoint

p95 en ms, corrida 1, ordenado por el p95 con 50 usuarios.

| Endpoint | p95 con 25 | p95 con 50 |
|---|---|---|
| `GET /inventory/movements` (todos) | 972 | 1,691 |
| `GET /commercial/clients/{id}/purchases` | 794 | 1,521 |
| `GET /inventory/analytics/monthly` | 779 | 1,445 |
| `GET /inventory/analytics/trend` | 661 | 1,436 |
| `GET /commercial/clients` | 782 | 1,399 |
| `GET /commercial/sales/{id}` | 511 | 1,394 |
| `GET /inventory/supplier-products` | 686 | 1,371 |
| `GET /inventory/products` | 741 | 1,325 |
| `GET /inventory/movements?product_id=` | 613 | 1,309 |
| `POST /inventory/movements` | 651 | 1,302 |
| `GET /analytics/sales/trend` | 766 | 1,279 |
| `GET /inventory/alerts` | 639 | 1,270 |
| `GET /analytics/sales/top-products` | 703 | 1,245 |
| `GET /analytics/sales/metrics` | 558 | 1,222 |
| `GET /inventory/suppliers` | 759 | 1,194 |
| `GET /inventory/history` | 573 | 1,185 |
| `GET /inventory/metrics` | 664 | 1,161 |
| `GET /tasks` | 504 | 1,132 |
| `GET /inventory/analytics/products` | 617 | 1,012 |
| `GET /health` (control) | 104 | 136 |

Bajo carga todos los endpoints tienen un p95 parecido, incluso `GET /tasks`, que
devuelve 20 filas. El tiempo se va en esperar turno, no en el trabajo propio de
cada endpoint. Para ver ese trabajo propio se midió cada endpoint 30 veces sin
concurrencia:

| Endpoint | Mediana ms | Tamaño de respuesta | Peso en la mezcla | Parte del tiempo del servidor |
|---|---|---|---|---|
| `GET /inventory/movements` (todos) | 215.4 | 7.2 MB | 2 | 32.8 % |
| `GET /inventory/analytics/monthly` | 61.6 | 2 KB | 5 | 23.5 % |
| `GET /commercial/clients` | 14.6 | 75 KB | 7 | 7.8 % |
| `GET /inventory/products` | 10.2 | 379 KB | 10 | 7.8 % |
| `GET /inventory/analytics/products` | 13.2 | 3 KB | 5 | 5.0 % |
| `GET /inventory/analytics/trend` | 10.7 | 6 KB | 5 | 4.1 % |
| `GET /commercial/clients/{id}/purchases` | 9.5 | 11 KB | 5 | 3.6 % |
| `GET /inventory/history` | 5.6 | 6 KB | 8 | 3.4 % |
| `GET /inventory/metrics` | 6.9 | 157 B | 6 | 3.1 % |
| Los 11 restantes | 0.4 a 4.1 | | 47 | 8.9 % |

El costo medio ponderado es de 13.1 ms por solicitud, lo que limita a un proceso a
unas 76 solicitudes por segundo. Es lo que se midió con carga (71 a 79). Dos
endpoints se llevan más de la mitad del tiempo: la lista completa de movimientos
(2 % de las solicitudes, un tercio del tiempo) y el análisis mensual.

### p95 frente al objetivo

El objetivo de p95 menor a 200 ms no se cumple en ningún nivel: con 25 usuarios
el p95 es de 3 a 4 veces el objetivo y con 100 la API deja de responder. El
segundo problema es más grave que el primero, porque no se recupera solo.
