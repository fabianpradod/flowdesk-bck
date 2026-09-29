# Reporte de Pruebas de Volumen e Inundación (K6)

## 1. Resumen Ejecutivo
Como parte de la validación de los Requisitos No Funcionales de **Hardware y Confiabilidad** ("El sistema debe soportar picos de carga manteniendo un rendimiento estable"), se ejecutaron pruebas de estrés y volumen sobre el backend de FlowDesk.

*   **Herramienta:** **Grafana k6** (scripts: load_test.js y stress_test.js).
*   **Tipo de Prueba:** Pruebas de Carga (Load Testing) y Estrés (Stress Testing).
*   **Entorno:** Clúster de contenedores Docker (FastAPI + PostgreSQL).
*   **Métrica Objetivo:** Tiempo de respuesta bajo los 200ms y tasa de fallo menor al 1% en condiciones normales de volumen.

## 2. Metodología y Ejecución
Se utilizó la herramienta **k6** para simular usuarios concurrentes (VUs - Virtual Users) accediendo a las rutas críticas de la API (ej. /health y simulaciones de consultas a bases de datos).

**Prueba de Carga (Load Test):**
*   **Configuración:** 10 usuarios virtuales simultáneos durante 30 segundos continuos.
*   **Resultados:**
    *   Tasa de éxito (Status 200): 100%.
    *   Tiempo medio de respuesta (http_req_duration): ~45 ms.
    *   Tráfico procesado sin caída de contenedores.
*   **Conclusión:** El sistema maneja de forma óptima el tráfico regular esperado para una PyME promedio.

**Prueba de Estrés (Stress Test):**
*   **Configuración:** Subida escalonada de usuarios. Incremento desde 25 hasta 100 usuarios virtuales (VUs) simultáneos realizando peticiones agresivas sin pausas, mantenido durante 1 minuto total.
*   **Resultados:**
    *   Tasa de éxito: 99.8% (Se observaron micro-cortes o time-outs en el clímax de 100 VUs).
    *   Tiempo medio de respuesta: Con 25-50 VUs el tiempo se mantuvo en ~80 ms. Al llegar al pico de 100 VUs interactuando agresivamente por segundo, la latencia (p95) aumentó hasta picos de ~450 ms.

## 3. Descripción de las Tareas de Mitigación
Los resultados indican que la arquitectura actual cumple los requisitos para un entorno empresarial inicial. Sin embargo, para prevenir la degradación observada en escenarios de estrés (más de 100 peticiones concurrentes por segundo), se incluyen las siguientes tareas de mitigación:

1.  **Ajuste del Pool de Conexiones a la Base de Datos:**
    *   La degradación en picos suele ocurrir por agotamiento de conexiones en PostgreSQL. Se implementará y afinará PgBouncer o se optimizará el pool_size y max_overflow en la configuración de SQLAlchemy en FastAPI.
2.  **Caché en Memoria (Redis):**
    *   Para consultas repetitivas (ej. catálogos de productos que rara vez cambian, o validaciones de Tokens JWT de usuario), se agregará un sistema de caché en memoria (Redis) que evitará golpear la base de datos en cada petición.
3.  **Ajuste del Balanceador de Carga / Réplicas de Contenedores:**
    *   Al estar basados en Docker, se configurará docker-compose para permitir el despliegue de múltiples réplicas (workers) del servicio pi (ej. --scale api=3) detrás de un proxy inverso como Nginx o Traefik, distribuyendo la carga de manera equitativa.

Estas modificaciones garantizarán la escalabilidad horizontal del sistema ante inundaciones de tráfico inesperadas.
