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

## Stack

- FastAPI
- PostgreSQL
- SQLAlchemy
- Docker + Docker Compose
- AWS EC2