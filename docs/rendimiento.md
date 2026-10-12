# Rendimiento del backend bajo carga

Revisión de la gestión de conexiones y de las consultas del backend para mantener
tiempos de respuesta adecuados con alta concurrencia. Medido sobre `main` en
`f5fe052`, octubre de 2026.

## Resumen

- **Bloqueo con alta concurrencia.** Desde unas 55 solicitudes simultáneas, los 40
  hilos de la API quedaban esperando una conexión que tenían otras solicitudes, que
  a su vez esperaban un hilo. La API dejaba de responder, devolvía 500 cada 30 s y
  no se recuperaba al bajar la carga. Se corrigió con el pool configurable (20 + 20
  conexiones por defecto) y un límite de solicitudes dentro de la aplicación igual
  al tamaño del pool.
- **Trabajo por solicitud.** La API es un solo proceso de Python y la base de datos
  casi no trabaja: el costo está en convertir filas y validar respuestas. Se
  quitaron 2 consultas por solicitud en la autenticación, una validación de correo
  repetida en la lista de clientes, trabajo por fila en la analítica y un N+1 en el
  historial de compras. El costo medio por solicitud bajó de 13.1 a 9.7 ms.
- **Resultado.** Con 100 usuarios simultáneos la API pasó de detenerse a atender
  unas 100 solicitudes por segundo sin errores. Con 25 y 50 usuarios el
  rendimiento subió entre 34 y 54 % y el p95 bajó entre 12 y 33 %.
- **Pendiente.** El p95 sigue sobre el objetivo de 200 ms. Llegar ahí pide paginar
  la lista completa de movimientos y más de un proceso (ver recomendaciones).

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

## Configuración de SQLAlchemy y pool de conexiones

### Configuración en main

- `app/core/database.py` crea el engine con `pool_pre_ping=True` y
  `pool_recycle=3600`, sin tamaño de pool. Quedan los valores por defecto de
  `QueuePool`: 5 conexiones fijas, 10 extra y 30 s de espera máxima. Un proceso
  de la API abre como máximo 15 conexiones.
- `get_db` entrega una `Session` por solicitud. La conexión se toma del pool con
  la primera consulta, que es la de `get_current_user`, y vuelve al pool cuando
  la dependencia cierra la sesión. En FastAPI 0.119 eso pasa después de enviar
  la respuesta completa. Cada solicitud retiene su conexión desde la
  autenticación hasta el último byte de la respuesta.
- `get_current_user` hace tres consultas por solicitud: el usuario y, por carga
  diferida, su empresa y su rol (7,515, 7,515 y 7,217 llamadas en la corrida 2).
  Cada una tarda unos 0.004 ms en PostgreSQL.
- `pool_pre_ping` agrega un ping por cada préstamo de conexión. Es barato contra
  una base local y protege de conexiones cortadas, así que se mantiene.
- Las 68 rutas son funciones `def` síncronas. FastAPI ejecuta cada dependencia
  síncrona, el endpoint y la validación de la respuesta como pasos separados en
  el pool de hilos de AnyIO, que tiene 40 hilos.

### Dónde se va el tiempo

En una corrida de 150 s, PostgreSQL ejecutó consultas durante 17.4 s en total.
El proceso de la API, en cambio, usó un núcleo completo todo el tiempo (1.05 s de
CPU por segundo, medido). El cuello de botella es el trabajo en Python
(convertir filas, validar y serializar respuestas), no la base de datos. Un solo
proceso de Python ejecuta ese trabajo de a una solicitud a la vez.

### El bloqueo del pool

Con la API instrumentada (muestras cada 0.5 s del pool y de los hilos) se ve qué
pasa al llegar a 100 usuarios:

| Segundo | Conexiones prestadas | Hilos esperando conexión | Préstamos en 0.5 s | Espera máxima ms | CPU |
|---|---|---|---|---|---|
| 20 (25 usuarios) | 14 | 6 | 22 | 1,084 | 1.03 |
| 60 (50 usuarios) | 15 | 31 | 79 | 888 | 1.08 |
| 93 (rampa a 100) | 15 | 33 | 57 | 1,424 | 1.06 |
| 96 | 15 | 40 | 0 | | 0.01 |
| 110 | 15 | 40 | 0 | | 0.00 |
| 124 | 15 | 40 | 14 | 30,005 | 0.21 |
| 140 | 15 | 40 | 0 | | 0.00 |
| 180 (k6 ya terminó) | 15 | 40 | 0 | | 0.00 |

El mecanismo:

1. Una solicitud toma una conexión en `get_current_user` y suelta el hilo.
2. Para el siguiente paso (el chequeo de rol, el endpoint o la validación de la
   respuesta) necesita otro hilo, y se pone en la fila con la conexión en la mano.
3. Mientras tanto, solicitudes nuevas toman los hilos libres y se quedan
   bloqueadas en `get_current_user` esperando una conexión.
4. Cuando los 40 hilos están esperando una conexión y las 15 conexiones son de
   solicitudes que esperan un hilo, nadie puede avanzar. Solo se destraba cuando
   vence la espera de 30 s del pool, con errores 500, y vuelve a trabarse.

Pasa desde unas 55 solicitudes simultáneas (15 conexiones más 40 hilos). Peor
aún, el bloqueo sigue después de que la carga termina, porque las solicitudes
que los clientes ya abandonaron siguen en la fila.

### Experimentos

Mismo escenario, cambiando solo la configuración del pool desde fuera del código.

| Configuración | Primer bloqueo | Muestras bloqueadas | Con 100 usuarios |
|---|---|---|---|
| 5 + 10 (main) | segundo 95 | 169 de 356 | 0 solicitudes/s, errores 500 |
| 20 + 20 | segundo 108 | 57 de 278 | 24 solicitudes/s, p95 30.9 s, 7 % de errores |
| 20 + 20 y un máximo de 40 solicitudes dentro de la aplicación | nunca | 0 de 272 | 70 solicitudes/s, p95 2.0 s, 0 errores |

Un pool más grande solo mueve el umbral (a 40 + 40 = 80 solicitudes). Lo que
elimina el bloqueo es no dejar entrar más solicitudes de las que el pool puede
atender: si dentro de la aplicación nunca hay más solicitudes que conexiones,
ninguna espera una conexión con un hilo tomado, y las demás esperan en el event
loop sin ocupar hilos ni conexiones. Con eso ningún hilo esperó una conexión en
toda la corrida.

El p95 de 2 s con 100 usuarios no es un bloqueo sino la fila: un proceso atiende
unas 75 solicitudes por segundo y 100 solicitudes simultáneas esperan su turno.
Bajarlo requiere menos trabajo de Python por solicitud o más procesos.

## Cambios en el pool

- `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT` y `DB_POOL_RECYCLE` se leen
  del entorno (`app/core/config.py`). Por defecto 20, 20, 30 s y 3600 s.
- 20 + 20 = 40 conexiones, las mismas que hilos tiene la API. Con el límite de
  admisión, 20 + 20 y 40 + 0 midieron lo mismo (68 y 69 solicitudes/s con 100
  usuarios, sin errores); 20 + 20 abrió solo 59 conexiones en toda la corrida y deja
  menos conexiones ociosas cuando no hay carga.
- `PoolAdmissionMiddleware` (`app/core/pool_admission.py`) deja entrar como máximo
  `DB_POOL_SIZE + DB_MAX_OVERFLOW` solicitudes a la vez. Las demás esperan su turno
  en el event loop, sin ocupar hilo ni conexión. `/health` queda fuera del límite.
  Se agrega antes de las validaciones de host y HTTPS, para que una solicitud
  rechazada no espere turno.
- `tests/test_pool_admission.py` reproduce el bloqueo en pequeño: 4 hilos, un pool
  de 2 conexiones y 40 solicitudes. Sin el límite, 36 terminan en 500 por timeout
  del pool; con el límite, las 40 responden 200.

Una solicitud ocupa su lugar hasta enviar la respuesta completa, igual que ya
ocupaba su conexión. Un chat de IA puede ocupar uno hasta 60 s, con un máximo de 8
chats por proceso, así que siempre quedan al menos 32 lugares para el resto.

## Consultas costosas

`pg_stat_statements` durante la carga, `EXPLAIN ANALYZE` y un perfil de Python por
endpoint mostraron que el tiempo no está en PostgreSQL sino en el número de viajes
a la base y en el trabajo por fila en Python.

| Hallazgo | Medición | Cambio |
|---|---|---|
| La autenticación hace 3 consultas por solicitud | usuario, empresa y rol: 7,515, 7,515 y 7,217 llamadas por corrida | `get_current_user` carga empresa y rol en la misma consulta |
| La lista de clientes valida otra vez cada correo guardado | 10 de los 14.6 ms de `GET /commercial/clients` con 300 clientes | `ClientResponse.correo` es texto; la entrada sigue validando el correo y la respuesta lo sigue normalizando |
| La analítica por periodo arma un acumulador nuevo por fila y lo descarta | 600 acumuladores para 2 meses, cada uno con `strftime` y 5 `Decimal` | Un acumulador por periodo y el puntaje de riesgo una vez por producto |
| La analítica mensual y de tendencia lee columnas que no usa | id, SKU, nombre y stock del producto convertidos en cada una de unas 10,000 filas | Leen 4 columnas, sin JOIN con producto |
| El historial de compras de un cliente hace un N+1 | 2 consultas más 2 por venta: 42 con 20 ventas | 3 consultas: cliente, página de ventas y todas sus líneas |

`tests/test_query_efficiency.py` cuenta las consultas contra SQLite y cubre cada
cambio. Además se compararon 92 respuestas de `main` y de la rama sobre la misma
base: son idénticas.

Costo propio de cada endpoint, mediana de 30 llamadas sin concurrencia:

| Endpoint | main ms | rama ms | Cambio |
|---|---|---|---|
| `GET /inventory/analytics/monthly` | 61.6 | 27.0 | -56 % |
| `GET /commercial/clients` | 14.6 | 3.1 | -79 % |
| `GET /inventory/analytics/products` | 13.2 | 11.3 | -14 % |
| `GET /inventory/analytics/trend` | 10.7 | 6.3 | -41 % |
| `GET /commercial/clients/{id}/purchases` | 9.5 | 2.8 | -71 % |
| `GET /inventory/movements` (todos) | 215.4 | 208.9 | sin cambio |
| Costo medio ponderado de la mezcla | 13.1 | 9.7 | -26 % |

### Lo que no se cambió

- **`GET /inventory/movements` sin filtro** devuelve los 20,000 movimientos (7.2 MB,
  209 ms). Es el 2 % de las solicitudes y ya el 43 % del tiempo del servidor.
  Corregirlo requiere paginar, lo que cambia el contrato con el frontend.
- **Índices.** Con este volumen las consultas filtradas recorren la tabla completa
  en muy poco tiempo y un índice no cambiaría el resultado:

  | Consulta | Plan | Tiempo |
  |---|---|---|
  | Movimientos de un producto (20,000 filas) | Seq Scan | 0.9 ms |
  | Analítica de 6 meses (devuelve la mitad de la tabla) | Seq Scan | 3.9 ms |
  | Ventas de un cliente (5,000 filas) | Seq Scan | 0.3 ms |
  | Líneas de una página de ventas (15,000 filas) | Seq Scan | 1.1 ms |

- **Agregar la analítica en SQL.** El análisis mensual sigue en 27 ms porque trae
  unas 10,000 filas a Python. Pasar la suma a `GROUP BY` en PostgreSQL lo bajaría
  más, pero las pruebas de analítica actuales alimentan filas crudas al servicio y
  habría que reescribirlas.

## Antes y después

Mismo escenario, misma base y misma máquina. Dos corridas por versión; cada celda
muestra corrida 1 / corrida 2.

| Usuarios | Versión | Solicitudes/s | p50 ms | p95 ms | p99 ms | Errores |
|---|---|---|---|---|---|---|
| 25 | main | 79 / 79 | 242 / 269 | 715 / 629 | 924 / 877 | 0 % |
| 25 | rama | 110 / 106 | 158 / 186 | 540 / 553 | 758 / 865 | 0 % |
| 50 | main | 74 / 71 | 550 / 608 | 1,325 / 1,339 | 1,787 / 1,782 | 0 % |
| 50 | rama | 114 / 98 | 397 / 435 | 893 / 1,026 | 1,073 / 1,447 | 0 % |
| 100 | main | se detiene | | | | 500 por timeout del pool |
| 100 | rama | 108 / 96 | 876 / 985 | 1,505 / 1,696 | 1,847 / 2,111 | 0 % |

En la corrida completa (2 min 25 s), `main` completó 8,076 y 7,727 solicitudes con
86 y 87 fallidas; la rama completó 16,683 y 15,679 sin ninguna falla.

### Qué aportó cada cambio

| Configuración | 25 usuarios | 50 usuarios | 100 usuarios |
|---|---|---|---|
| main | 79 req/s, p95 715 ms | 74 req/s, p95 1,325 ms | se detiene |
| Solo pool 20 + 20 y límite de admisión | 72 req/s, p95 728 ms | 72 req/s, p95 1,190 ms | 70 req/s, p95 1,969 ms, 0 errores |
| Rama completa (pool, límite y consultas) | 110 req/s, p95 540 ms | 114 req/s, p95 893 ms | 108 req/s, p95 1,505 ms, 0 errores |

La segunda fila se midió con el código de `main`, cambiando el pool y agregando el
límite desde fuera del código. El pool y el límite quitan el bloqueo; las
optimizaciones de consultas suben el rendimiento entre 35 y 55 % y bajan el p95.

### p95 por endpoint con 50 usuarios

| Endpoint | main ms | rama ms | Cambio corrida 1 | Cambio corrida 2 |
|---|---|---|---|---|
| `GET /inventory/movements` (todos) | 1,691 | 1,139 | -33 % | -25 % |
| `GET /commercial/clients/{id}/purchases` | 1,521 | 816 | -46 % | -26 % |
| `GET /inventory/analytics/monthly` | 1,445 | 974 | -33 % | -16 % |
| `GET /inventory/analytics/trend` | 1,436 | 882 | -39 % | -22 % |
| `GET /commercial/clients` | 1,399 | 863 | -38 % | -23 % |
| `GET /commercial/sales/{id}` | 1,394 | 746 | -46 % | -31 % |
| `GET /inventory/supplier-products` | 1,371 | 747 | -46 % | -25 % |
| `GET /inventory/products` | 1,325 | 933 | -30 % | -21 % |
| `GET /inventory/movements?product_id=` | 1,309 | 856 | -35 % | -16 % |
| `POST /inventory/movements` | 1,302 | 911 | -30 % | -19 % |
| `GET /analytics/sales/trend` | 1,279 | 883 | -31 % | -24 % |
| `GET /inventory/alerts` | 1,270 | 739 | -42 % | -13 % |
| `GET /analytics/sales/top-products` | 1,245 | 969 | -22 % | -26 % |
| `GET /analytics/sales/metrics` | 1,222 | 826 | -32 % | -31 % |
| `GET /inventory/suppliers` | 1,194 | 874 | -27 % | -40 % |
| `GET /inventory/history` | 1,185 | 855 | -28 % | -33 % |
| `GET /inventory/metrics` | 1,161 | 870 | -25 % | -23 % |
| `GET /tasks` | 1,132 | 852 | -25 % | -38 % |
| `GET /inventory/analytics/products` | 1,012 | 929 | -8 % | -27 % |
| `GET /health` (control) | 136 | 230 | +69 % | +11 % |

Todos los endpoints con base de datos bajan, también los que no se tocaron, porque
la fila delante de cada solicitud se mueve más rápido. `GET /health` no usa la base
y sube un poco: comparte el mismo núcleo con un 40 % más de solicitudes por
segundo.

### El objetivo de 200 ms

El p95 sigue por encima de 200 ms. Con solicitudes sin pausa, el tiempo medio de
respuesta es el número de solicitudes en curso dividido entre las que el servidor
completa por segundo: con 100 usuarios, 100 / 108 = 0.93 s. Un proceso atiende
unas 105 solicitudes por segundo con esta mezcla, así que un p95 de 200 ms con 100
solicitudes simultáneas pide del orden de 500 por segundo: varios procesos además
de menos trabajo por solicitud (ver recomendaciones).

## Recomendaciones

1. **Paginar `GET /inventory/movements`** (`limit` y `offset`, como ya tiene el
   historial de compras) y que el frontend pida páginas. Es el mayor consumo de CPU
   que queda.
2. **Más de un proceso.** Un proceso de Python usa un solo núcleo. Con `--workers`
   o réplicas, cada proceso tiene su propio pool y su propio límite: con el valor
   por defecto son 40 conexiones por proceso, y PostgreSQL acepta 100 en la imagen
   de Compose. Dos procesos caben; para más, bajar `DB_POOL_SIZE` y
   `DB_MAX_OVERFLOW` o poner PgBouncer delante.
3. **Analítica en SQL** cuando se reescriban sus pruebas.
4. **Índices cuando crezcan los datos**: `movimiento_inventario (producto_id,
   fecha)`, `venta (cliente_id, fecha)` y `detalle_venta (venta_id)`. Con unas 10
   veces el volumen actual, cada recorrido completo pasaría a unos 10 ms
   (estimación lineal).
5. **Medir en EC2** con el mismo escenario. Las cifras de este documento son de una
   máquina local y sirven para comparar, no como latencia de producción.
6. **Un escenario con pausas entre acciones** si el objetivo se quiere expresar en
   usuarios reales. Sin pausas, 100 usuarios virtuales son 100 solicitudes
   simultáneas todo el tiempo.
