"""
Services/auth.py — Autenticación y control de acceso contra PostgreSQL
=====================================================================

Valida credenciales contra las tablas existentes de la base `TrabajoGrado`:

    public.usuario(nombre, correo PK, contrasena)
    public.rol_usuario(fkcorreo -> usuario.correo, fkid -> rol.id)
    public.rol(id, nombre)              -- 'Administrador' / 'Consultor'

No crea usuarios ni roles: usa los que ya están en la BD.  Roles internos:
  • admin     (rol 'Administrador') — acceso total, inicia en Inicio.
  • consultor (rol 'Consultor')     — solo la Landing Ejecutiva.

La conexión usa la misma config Postgres del proyecto (configurable por
variables de entorno).
"""

import os

import psycopg2

# ── Conexión Postgres ────────────────────────────────────────────────────────
PG_HOST     = os.environ.get("TG_DB_HOST", "localhost")
PG_PORT     = int(os.environ.get("TG_DB_PORT", "5432"))
PG_DATABASE = os.environ.get("TG_DB_NAME", "TrabajoGrado")
PG_USER     = os.environ.get("TG_DB_USER", "postgres")
PG_PASSWORD = os.environ.get("TG_DB_PASSWORD", "postgres")

# ── Rutas clave ──────────────────────────────────────────────────────────────
LOGIN_PATH   = "/login"
HOME_PATH    = "/"                       # Página de Inicio (menú principal)
LANDING_PATH = "/resumen-ejecutivo"      # Landing Ejecutiva
NO_NAVBAR_PATHS = {HOME_PATH, LOGIN_PATH, LANDING_PATH}

# Nombre del rol en la BD → rol interno usado por el control de acceso.
_ROLE_MAP = {"administrador": "admin", "consultor": "consultor"}


def _connect():
    return psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=PG_DATABASE,
                            user=PG_USER, password=PG_PASSWORD, connect_timeout=8)


def check_credentials(correo, password):
    """Valida (correo, contraseña) contra la BD. Devuelve dict del usuario
    {name, correo, role} si es válido, o None."""
    correo = (correo or "").strip()
    if not correo or password is None:
        return None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.nombre, u.correo, r.nombre
            FROM public.usuario u
            JOIN public.rol_usuario ru ON ru.fkcorreo = u.correo
            JOIN public.rol r          ON r.id = ru.fkid
            WHERE lower(u.correo) = lower(%s) AND u.contrasena = %s
            LIMIT 1
            """,
            (correo, password),
        )
        row = cur.fetchone()
        conn.close()
    except Exception:
        return None
    if not row:
        return None
    nombre, correo_db, rol_db = row
    role = _ROLE_MAP.get((rol_db or "").strip().lower())
    if not role:
        return None
    return {"name": nombre, "correo": correo_db, "role": role}


def can_access(role, path):
    """¿El rol puede ver esta ruta?"""
    if role == "admin":
        return True
    if role == "consultor":
        return path == LANDING_PATH
    return False


def landing_for(role):
    """Ruta inicial tras iniciar sesión según el rol."""
    return LANDING_PATH if role == "consultor" else HOME_PATH
