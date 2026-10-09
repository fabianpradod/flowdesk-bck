# Sprint 9: mitigaciones de seguridad

Fecha: 9 de octubre de 2026. Historia SCRUM-620, subtareas SCRUM-621–633.
La implementación está validada localmente. No se ha desplegado ni cerrado tickets
Jira. La aceptación de riesgos corresponde al equipo, no a esta implementación.

## Alcance y evidencia

No había reporte OWASP ZAP original en el repositorio; SCRUM-621 y la historia
padre tampoco contienen descripción o adjuntos visibles. Se generó una nueva
línea base local sobre HEAD `00030da0b0026f9b7a2feb5797c3bd5956b40953` y se
comparó con los cambios de este sprint. No representa el escaneo histórico del
sistema desplegado ni incluye el frontend.

| Ticket | Resultado local | Evidencia / límite |
|---|---|---|
| SCRUM-621 | Línea base ZAP revisada | `zap-before.json/html`; falta contrastar reporte histórico si existe |
| SCRUM-622 | CSP evaluada | API JSON restrictiva y excepción específica para documentación |
| SCRUM-623 | CSP implementada | `app/core/https.py`; scripts de docs autorizados por SHA-256 |
| SCRUM-624 | MIME sniffing bloqueado | `X-Content-Type-Options: nosniff`, también en errores |
| SCRUM-625 | Referrer limitado | `strict-origin-when-cross-origin`, también en errores |
| SCRUM-626 | Framing bloqueado | `X-Frame-Options: DENY` y `frame-ancestors 'none'` |
| SCRUM-627 | CORS revisado y restringido | Orígenes explícitos; override de producción; métodos/headers limitados; 500 cubiertos |
| SCRUM-628 | Errores internos revisados | Suite de errores: SQL, esquema, contraseña y traceback no llegan al cliente |
| SCRUM-629 | Endpoints sensibles validados en pruebas | Suites de inventario de rutas, autenticación, roles y aislamiento tenant; persistencia simulada |
| SCRUM-630 | ZAP repetido localmente | `zap-after.json/html`; baseline pasivo sin sesión |
| SCRUM-631 | Comparativo realizado | Tabla de alertas abajo; sin afirmación de ausencia de vulnerabilidades |
| SCRUM-632 | Mitigaciones documentadas | Este archivo, README principal y `.env.example` |
| SCRUM-633 | Registro de riesgos preparado | Riesgos residuales abajo; aceptación pendiente del equipo |

## Implementación

`SecureFastAPI` envuelve la pila completa, por fuera de ServerErrorMiddleware.
Así, los headers y CORS también cubren los errores 500 inesperados. Los errores
mantienen el contrato JSON existente; no se modifica la matriz de permisos.

La API devuelve:

```text
Content-Security-Policy: default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Cache-Control: no-store
Cross-Origin-Resource-Policy: same-origin
```

La documentación requiere JavaScript y CSS de jsDelivr y fuentes Google.
Su CSP se calcula únicamente para HTML exitoso en `/docs`, `/redoc` y el callback
OAuth, incluyendo cuando se publica bajo un prefijo. Cada script inline recibe
un hash de su contenido exacto. No se permite `unsafe-inline` ni `unsafe-eval`
para scripts. Los estilos inline se conservan por compatibilidad con estas UI.
La API JSON nunca recibe esa excepción. Solo se acumula el HTML pequeño de docs;
los archivos y respuestas streaming pasan sin acumularse.

CORS permite credenciales únicamente para orígenes listados. `CORS_ORIGINS`
reemplaza los defaults locales, incluso si está vacío. Se permiten
GET/POST/PUT/PATCH/DELETE/OPTIONS y Authorization/Content-Type (además de los
headers simples del protocolo). CORS limita lectura desde navegadores y no es un
guard de autorización. `CORP: same-origin` bloquea cargas no-CORS desde otros
orígenes; no bloquea al frontend que usa CORS correctamente.

HSTS sigue condicionado a `FORCE_HTTPS=true` y ahora solo sale sobre HTTPS.
La validación de Host sucede antes de redirigir. Configurar hosts, TLS, proxy y
orígenes exactos sigue siendo una tarea de despliegue.

## Escaneo ZAP antes/después

ZAP 2.17.0, imagen oficial fijada por digest:
`ghcr.io/zaproxy/zaproxy@sha256:7aaa659b0d43078febd82e29bad112285c370727e86ab8340444220e17d9f0d2`.
Baseline con spider de 1 minuto y límite de 2 minutos, iniciado en `/docs`.
Cada escaneo descubrió 5 URLs. El proceso devuelve código 2 porque hay warnings;
no se suprimieron alertas ni se configuraron exclusiones.

| Alerta ZAP | Antes | Después | Interpretación |
|---|---|---|---|
| 10038-1 CSP no configurada | Media | Ausente | Mitigada |
| 90004-1 CORP ausente | Baja | Ausente | Mitigada |
| 10049-3 Contenido cacheable | Informativa | Ausente | Sustituida por `no-store` |
| 10049-1 Contenido no almacenable | Ausente | Informativa | Efecto esperado de `no-store` |
| 10055-6 CSP style-src unsafe-inline | Ausente | Media | Riesgo residual exclusivo de docs; antes no había CSP |
| 90003 SRI ausente en recursos externos | Media | Media | Pendiente en docs |
| 10017 JavaScript de otro dominio | Baja | Baja | CDN de documentación |
| 90004-2 COEP ausente | Baja | Baja | Pendiente en docs |
| 90004-3 COOP ausente | Baja | Baja | Pendiente en docs |
| 10063-1 Permissions Policy ausente | Baja | Baja | Pendiente en docs |
| 10109 Aplicación web moderna | Informativa | Informativa | Clasificación del contenido, no prueba de explotación |

Antes: 2 alertas medias, 5 bajas y 2 informativas. Después: 2 medias, 4 bajas y
2 informativas, contadas por `alertRef` en JSON. La salida CLI agrupa referencias:
7 grupos WARN en ambos escaneos, 0 FAIL y 60 PASS. Los PASS solo indican que esa
regla pasiva no encontró una alerta en las respuestas observadas.

El objetivo fue una copia local con rutas reales, servida mediante un puente
HTTP/TestClient. Se anuló `init_db` y se sustituyó `get_db` por una dependencia
sin conexión. `/ready` responde 503 a propósito. No hubo credenciales de sesión,
operaciones de negocio, envío de correo ni llamadas a Z.AI. Esto no verifica
TLS, PostgreSQL, proxy, autenticación en ZAP ni el servidor ASGI de producción.
Los permisos y errores internos se cubren separadamente con pruebas automatizadas.

### Reproducir

Crear un checkout del commit base en `/tmp/flowdesk-sprint9-before` y ejecutar en
dos terminales desde este repositorio:

```bash
.venv/bin/python scripts/security_scan_server.py 18766 /tmp/flowdesk-sprint9-before
.venv/bin/python scripts/security_scan_server.py 18769
```

El puente es exclusivamente local de pruebas; deniega métodos de mutación y no
inicializa la base. No usarlo para desplegar. En otra terminal, con un directorio
absoluto escribible de evidencia, ejecutar para cada puerto:

```bash
docker run --rm -v /tmp/flowdesk-sprint9-evidence:/zap/wrk/:rw \
  ghcr.io/zaproxy/zaproxy@sha256:7aaa659b0d43078febd82e29bad112285c370727e86ab8340444220e17d9f0d2 \
  zap-baseline.py -t http://host.docker.internal:18766/docs -m 1 -T 2 \
  -J before-docs.json -r before-docs.html
```

Cambiar a puerto 18769 y nombres `after-docs` para la segunda ejecución.
Referencia: [ZAP Baseline Scan](https://www.zaproxy.org/docs/docker/baseline-scan/).
La cobertura pasiva sin sesión es limitada; un escaneo autenticado requiere un
entorno descartable y usuarios de prueba.

## Riesgos residuales y aceptación

**Estado de aceptación: pendiente.** Esta tabla documenta riesgos; no concede
aceptación ni declara completado SCRUM-633.

| Riesgo | Tratamiento propuesto / condición de cierre |
|---|---|
| Estilos inline y dependencias CDN de docs sin SRI | Restringir/deshabilitar documentación pública o servir assets locales versionados con SRI; verificar Swagger/ReDoc al cambiarlo |
| COOP, COEP y Permissions Policy ausentes | Evaluar en el despliegue junto con CDN y callback OAuth antes de aplicar políticas que puedan romperlos |
| Localhost permitido en configuración por defecto | Configurar `CORS_ORIGINS` con el origen real en producción |
| HTTPS/Host opt-in y proxy fuera del escaneo | Activar TLS, FORCE_HTTPS y ALLOWED_HOSTS; verificar headers desde el exterior |
| CSP del frontend fuera de este repositorio | Implementar/verificar en el servidor que entrega el frontend |
| Reporte ZAP histórico no disponible | Adjuntarlo y contrastar sus hallazgos; no inferir que son iguales a la línea base local |
| Escaneo sin sesión ni base real | Repetir baseline y pruebas autenticadas con datos de prueba en staging |
| Recomendaciones F18–F25 de la revisión previa | Continúan pendientes; ver `docs/revision-seguridad.md` (rate limit, contraseñas, xlsx descomprimido, docs públicas, permisos de movimientos, SECRET_KEY, tiempos login y reset reutilizable) |

## Validación automatizada

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/test_sprint9_security.py tests/test_transport_security.py -q
```

Resultado final tras integrar `origin/main`: **2510 pruebas aprobadas, 5 omitidas
y 5 subtests aprobados**, en 14.93 segundos. Las omitidas requieren PostgreSQL descartable o llamadas
reales a Z.AI. El subconjunto de transporte/Sprint 9 aprobó 29 pruebas.

Las nuevas pruebas ejercitan respuestas 200/401/404/500, preflight permitido y
rechazado, CORS en 500, headers/métodos no autorizados, scripts de documentación
con hash válido, documentación bajo un prefijo, cuerpos de descarga, HSTS sobre
TLS y headers en rechazos de Host. Swagger y ReDoc también cargaron en navegador
sin errores de consola durante la comprobación manual.

El cierre de la historia requiere desplegar estos cambios, repetir la validación
externa y que el equipo acepte o mitigue los riesgos documentados. No se modificó
Jira durante la implementación.
