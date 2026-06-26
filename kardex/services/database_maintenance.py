import shutil
import sqlite3
import tempfile
from pathlib import Path

from django.conf import settings
from django.db import connections
from django.utils import timezone


class DatabaseMaintenanceError(Exception):
    pass


def _database_path():
    database = settings.DATABASES["default"]
    if database.get("ENGINE") != "django.db.backends.sqlite3":
        raise DatabaseMaintenanceError("El mantenimiento de DB solo esta disponible para SQLite.")
    return Path(database["NAME"])


def _backup_dir():
    backup_dir = Path(settings.BASE_DIR) / "backups" / "db"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _timestamp():
    return timezone.localtime().strftime("%Y%m%d-%H%M%S")


def crear_backup_base_datos(prefix="kardexml"):
    db_path = _database_path()
    if not db_path.exists():
        raise DatabaseMaintenanceError("No existe una base de datos local para respaldar.")

    backup_path = _backup_dir() / f"{prefix}-{_timestamp()}.sqlite3"
    connections.close_all()
    shutil.copy2(db_path, backup_path)
    return backup_path


def validar_sqlite(path):
    conn = None
    try:
        conn = sqlite3.connect(path)
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if not row or row[0].lower() != "ok":
            raise DatabaseMaintenanceError("El archivo SQLite no paso la verificacion de integridad.")
        tablas = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    except sqlite3.DatabaseError as exc:
        raise DatabaseMaintenanceError("El archivo subido no es una base SQLite valida.") from exc
    finally:
        if conn is not None:
            conn.close()

    tablas_minimas = {"auth_user", "django_migrations"}
    if not tablas_minimas.issubset(tablas):
        raise DatabaseMaintenanceError("El archivo no parece ser una base de datos de esta aplicacion.")


def restaurar_base_datos(uploaded_file):
    db_path = _database_path()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite3") as temp_file:
        temp_path = Path(temp_file.name)
        for chunk in uploaded_file.chunks():
            temp_file.write(chunk)

    try:
        validar_sqlite(temp_path)
        if not db_path.exists():
            raise DatabaseMaintenanceError("No existe una base de datos local para reemplazar.")
        backup_path = crear_backup_base_datos(prefix="pre-restore")
        connections.close_all()
        shutil.copy2(temp_path, db_path)
    finally:
        temp_path.unlink(missing_ok=True)

    return backup_path
