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

## Revisión del PR: composición de middleware y consumidores CORS

Verificado el 10 de octubre de 2026 contra el commit revisado `43326c4`.
`configure_transport_security()` contiene un solo registro de
`TrustedHostMiddleware`, con `allowed_hosts=config.ALLOWED_HOSTS`, y `main.py`
llama esa función una sola vez. No existe el segundo registro mencionado en la
revisión. No se eliminó código funcional ni se cambió la pila para simular una
corrección. Se añadieron pruebas de regresión de la pila real en las cuatro
combinaciones de HTTPS activado/desactivado y lista de hosts vacía/configurada.

Orden exterior → interior con ambas opciones activas:

```text
SecurityHeadersMiddleware
CORSMiddleware
ServerErrorMiddleware
TrustedHostMiddleware (una instancia)
HTTPSRedirectMiddleware (una instancia)
ExceptionMiddleware / AsyncExitStackMiddleware / router
```

Las pruebas verifican tanto la instancia única y el orden como el comportamiento:
host permitido responde, host ajeno responde 400 sin `Location`, host permitido
sobre HTTP redirige a HTTPS. CORS permanece exterior para cubrir errores 500;
los preflights son resueltos por CORS antes de entrar a los guards interiores.
Esto describe el comportamiento existente, sin atribuir validación de Host a
preflights que CORS resuelve directamente.

### Contrato del frontend comprobado

Se actualizó la referencia remota `master` de `yehosuah/flowdesk-frt` y se revisó
el commit **`fff1a7d9241008b6fd060f2c1adcd992c65c5085`**, sin modificar su checkout.
Se buscaron todas las construcciones y sobrescrituras de headers y llamadas
fetch/axios/XHR en `src` y `netlify`. No se encontraron headers personalizados
adicionales requeridos por esos consumidores. El cliente admite un argumento
`headers`, pero sus consumidores actuales no pasan overrides adicionales.

| Consumidor | Headers de solicitud observados | Métodos |
|---|---|---|
| [apiClient.ts](https://github.com/yehosuah/flowdesk-frt/blob/fff1a7d9241008b6fd060f2c1adcd992c65c5085/src/services/apiClient.ts#L113) y sus consumidores | Accept, Content-Type cuando hay JSON, Authorization cuando hay sesión | GET, POST, PUT, PATCH, DELETE |
| [Importación Excel](https://github.com/yehosuah/flowdesk-frt/blob/fff1a7d9241008b6fd060f2c1adcd992c65c5085/src/features/inventory/import.ts#L51) | Authorization; Content-Type multipart con boundary generado por el navegador | POST |
| [Descarga de reportes](https://github.com/yehosuah/flowdesk-frt/blob/fff1a7d9241008b6fd060f2c1adcd992c65c5085/src/features/reports/views/ReportsView.vue#L1232) | Authorization | GET |
| [Proxy Netlify](https://github.com/yehosuah/flowdesk-frt/blob/fff1a7d9241008b6fd060f2c1adcd992c65c5085/netlify/functions/proxy.ts#L17) hacia backend | Content-Type, Authorization opcional | Reenvía el método; es tráfico servidor a servidor, sin preflight de navegador |

`Accept` pertenece a los headers simples admitidos por CORSMiddleware. JSON,
Authorization y multipart quedan cubiertos por la política actual. Se añadieron
pruebas OPTIONS con estas combinaciones, incluidas descargas, importación,
PUT/PATCH/DELETE. No fue necesario ampliar `allow_headers` ni `allow_methods`.
La conclusión se limita al código versionado citado: no certifica otros clientes,
headers añadidos por infraestructura o la versión actualmente desplegada.

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

### Aceptación para este PR

**Riesgos formalmente aceptados: ninguno.** No hay una aprobación explícita del
equipo en la evidencia disponible. La excepción técnica de compatibilidad se
conserva en este PR y se propone para aceptación en la revisión; esto no equivale
a aceptar su exposición en producción ni a cerrar SCRUM-633. La aprobación del
código debe distinguirse de la aprobación de riesgos del despliegue.

| Excepción conservada / aceptación propuesta | Motivo y alcance | Riesgo que sigue existiendo |
|---|---|---|
| `style-src 'unsafe-inline'` (10055-6) | Swagger/ReDoc requieren estilos inline; solo HTML de documentación, nunca CSP de API JSON | Inyección de estilos si existe una vulnerabilidad HTML; scripts inline siguen restringidos por hashes |
| Recursos CDN de docs sin SRI (90003) y JavaScript externo (10017) | Se mantiene la carga de documentación existente de jsDelivr; CSP limita el dominio | Una alteración del recurso permitido por el CDN no queda impedida por SRI |

Responsable de aceptar o rechazar estas excepciones: equipo mantenedor y
responsable del despliegue. No se ha registrado esa aceptación. Si no se acepta,
se requiere restringir/deshabilitar docs públicas o servir assets versionados
locales con integridad y adaptar sus estilos antes de exponerlas.

### Mitigaciones pendientes

| Pendiente | Condición de cierre |
|---|---|
| Eliminar/reducir estilos inline y dependencia CDN sin SRI | Assets locales versionados/integridad, adaptación de estilos o docs restringidas; verificar Swagger/ReDoc |
| COOP, COEP y Permissions Policy ausentes (90004-2, 90004-3, 10063-1) | Evaluar e implementar políticas compatibles con CDN y callback OAuth; no se declaran aceptadas |
| Defaults locales y HTTPS/Host opt-in | Configurar `CORS_ORIGINS`, `FORCE_HTTPS`, `ALLOWED_HOSTS` y proxy con valores del entorno |
| CSP del frontend fuera de este repositorio | Implementar/verificar en el servidor que entrega el frontend |
| Reporte ZAP histórico no disponible | Adjuntarlo y contrastar sus hallazgos con esta línea base |
| Recomendaciones F18–F25 de la revisión previa | Continúan pendientes en `docs/revision-seguridad.md`; este PR no las declara resueltas ni aceptadas |

### Validaciones posteriores en staging/producción

Antes de dar por validado el despliegue, el responsable del entorno debe conservar
evidencia de estas comprobaciones:

1. Desde la URL pública real, verificar TLS/certificado, HSTS sobre HTTPS,
   redirección HTTP sin bucles detrás del proxy y rechazo de Host no autorizado.
2. Verificar CSP y demás headers en respuestas 200/401/403/404/422/500 y descargas,
   incluidos errores que emita el proxy; confirmar que no se cachean datos privados.
3. Desde el origen real del frontend, probar login, operaciones GET/POST/PUT/PATCH/
   DELETE, importación multipart y descarga; verificar preflight, headers que
   realmente añade infraestructura y rechazo de orígenes ajenos.
4. Repetir baseline ZAP sobre backend y frontend desplegados y un escaneo
   autenticado en staging con cuentas de prueba de distintos roles/tenants,
   PostgreSQL descartable y servicios externos controlados. No ejecutar ataques
   activos contra producción ni usar datos reales sin un alcance autorizado.
5. Verificar Swagger/ReDoc y callback OAuth si siguen habilitados; comprobar las
   mitigaciones decididas para CDN/SRI, estilos inline y políticas de aislamiento.
6. Registrar aceptación explícita, responsable, alcance y fecha para cada riesgo
   residual que se decida conservar. Hasta entonces SCRUM-633 sigue pendiente.

El baseline local de este PR no cumple por sí solo ninguna certificación de
producción ni cubre TLS/proxy, base real o todas las sesiones autenticadas.

## Validación automatizada

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/test_sprint9_security.py tests/test_transport_security.py -q
```

Resultado tras atender la revisión del PR (10 de octubre de 2026):
**2522 pruebas aprobadas, 5 omitidas y 5 subtests aprobados**, en 14.49 segundos. Las omitidas requieren PostgreSQL descartable o llamadas
reales a Z.AI. El subconjunto de transporte/Sprint 9 contiene 41 pruebas, incluidas las 12 nuevas de revisión.

Las nuevas pruebas ejercitan respuestas 200/401/404/500, preflight permitido y
rechazado, CORS en 500, headers/métodos no autorizados, scripts de documentación
con hash válido, documentación bajo un prefijo, cuerpos de descarga, HSTS sobre
TLS y headers en rechazos de Host. Swagger y ReDoc también cargaron en navegador
sin errores de consola durante la comprobación manual.

El cierre de la historia requiere desplegar estos cambios, repetir la validación
externa y que el equipo acepte o mitigue los riesgos documentados. No se modificó
Jira durante la implementación.
