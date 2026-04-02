-- PostgreSQL initialisation script for Prasine Index.
-- Runs once when the container is first created.
-- Creates required extensions. Tables are created by init_db() in core/database.py
-- on application startup; schema evolution is managed by Alembic.

CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
