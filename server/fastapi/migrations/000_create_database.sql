-- Запускать через psql от имени администратора PostgreSQL:
-- psql -U postgres -f 000_create_database.sql
--
-- Этот файл использует команды psql (\connect и \gexec), поэтому
-- его не нужно выполнять через SQLAlchemy/FastAPI.

\set ON_ERROR_STOP on

SELECT 'CREATE ROLE yago LOGIN PASSWORD ''yago'''
WHERE NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'yago'
) \gexec

SELECT format('CREATE DATABASE %I OWNER %I', 'yago', 'yago')
WHERE NOT EXISTS (
    SELECT 1
    FROM pg_database
    WHERE datname = 'yago'
) \gexec

\connect yago yago

CREATE EXTENSION IF NOT EXISTS pgcrypto;
