"""Modelos SQLAlchemy + setup Flask-SQLAlchemy.

Esquema multi-usuario:
- usuario: cuentas con email/password.
- tercero: directorio de NITs propio de cada usuario.
- tipo_documento: catálogo de tipos MUISCA. usuario_id NULL = default global.
- concepto_default: conceptos por defecto por formato y usuario.
- nit_no_encontrado: cache negativo de consultas remotas.
- generacion: historial de generaciones (opcional).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, inspect, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


def _codigo_dane(valor, ancho: int) -> str | None:
    if valor in (None, "", 0):
        return None
    digits = "".join(ch for ch in str(valor).strip() if ch.isdigit())
    if not digits or set(digits) == {"0"}:
        return None
    if len(digits) <= ancho:
        return digits.zfill(ancho)
    return digits[:ancho] if ancho == 2 else digits[-ancho:]


class Usuario(UserMixin, db.Model):
    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nombre: Mapped[str] = mapped_column(String(255), default="")
    es_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    terceros: Mapped[list["Tercero"]] = relationship(back_populates="usuario", cascade="all, delete-orphan")
    tipos_documento: Mapped[list["TipoDocumento"]] = relationship(back_populates="usuario", cascade="all, delete-orphan")
    conceptos: Mapped[list["ConceptoDefault"]] = relationship(back_populates="usuario", cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Tercero(db.Model):
    __tablename__ = "tercero"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id", ondelete="CASCADE"), index=True)
    nid: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    tdoc: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    dv: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    raz: Mapped[Optional[str]] = mapped_column(String(450), nullable=True)
    apl1: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    apl2: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    nom1: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    nom2: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    direccion: Mapped[Optional[str]] = mapped_column("dir", String(200), nullable=True)
    dpto: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    mun: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    pais: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=169)
    fuente: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    usuario: Mapped[Usuario] = relationship(back_populates="terceros")

    __table_args__ = (
        UniqueConstraint("usuario_id", "nid", name="uq_tercero_usuario_nid"),
    )

    def to_dict(self) -> dict:
        out = {
            "nid": self.nid,
            "tdoc": self.tdoc,
            "dv": self.dv,
            "raz": self.raz or "",
            "apl1": self.apl1 or "",
            "apl2": self.apl2 or "",
            "nom1": self.nom1 or "",
            "nom2": self.nom2 or "",
            "dir": self.direccion or "",
            "dpto": _codigo_dane(self.dpto, 2),
            "mun": _codigo_dane(self.mun, 3),
            "pais": self.pais,
        }
        return {k: v for k, v in out.items() if v not in (None, "")}


class TipoDocumento(db.Model):
    __tablename__ = "tipo_documento"

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL = default global del sistema (semilla)
    usuario_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuario.id", ondelete="CASCADE"), nullable=True, index=True)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    categoria: Mapped[str] = mapped_column(String(50), nullable=False)
    signo: Mapped[int] = mapped_column(Integer, default=1)

    usuario: Mapped[Optional[Usuario]] = relationship(back_populates="tipos_documento")

    __table_args__ = (
        UniqueConstraint("usuario_id", "nombre", name="uq_tipo_doc_usuario_nombre"),
    )


class ConceptoDefault(db.Model):
    __tablename__ = "concepto_default"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id", ondelete="CASCADE"), index=True)
    formato: Mapped[str] = mapped_column(String(4))
    concepto: Mapped[int] = mapped_column(Integer)

    usuario: Mapped[Usuario] = relationship(back_populates="conceptos")

    __table_args__ = (
        UniqueConstraint("usuario_id", "formato", name="uq_concepto_usuario_formato"),
    )


class NitNoEncontrado(db.Model):
    __tablename__ = "nit_no_encontrado"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id", ondelete="CASCADE"), index=True)
    nid: Mapped[str] = mapped_column(String(20), index=True)
    fuente: Mapped[str] = mapped_column(String(50), default="RUES")
    fecha: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("usuario_id", "nid", "fuente", name="uq_nonenc_usuario_nid_fuente"),
    )


class Generacion(db.Model):
    """Historial de generaciones. Solo metadatos; los XLSX se entregan en memoria."""
    __tablename__ = "generacion"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id", ondelete="CASCADE"), index=True)
    nit_informante: Mapped[str] = mapped_column(String(20))
    nombre_informante: Mapped[str] = mapped_column(String(450), default="")
    ano_gravable: Mapped[int] = mapped_column(Integer)
    mes_inicio: Mapped[int] = mapped_column(Integer, default=1)
    mes_fin: Mapped[int] = mapped_column(Integer, default=12)
    archivo_origen: Mapped[str] = mapped_column(String(255), default="")
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---- helpers de contexto ----

def usuario_actual_id() -> int:
    """Devuelve el id del usuario logueado o lanza si no hay sesión."""
    from flask_login import current_user  # import diferido para no acoplar
    if not getattr(current_user, "is_authenticated", False):
        raise RuntimeError("No hay usuario en sesión")
    return int(current_user.id)


def migrar_codigos_territoriales() -> None:
    """Convierte dpto/mun de entero a texto para conservar ceros a la izquierda."""
    inspector = inspect(db.engine)
    if "tercero" not in inspector.get_table_names():
        return

    columnas = {c["name"]: c for c in inspector.get_columns("tercero")}
    dpto_es_texto = isinstance(columnas.get("dpto", {}).get("type"), String)
    mun_es_texto = isinstance(columnas.get("mun", {}).get("type"), String)
    dialecto = db.engine.dialect.name

    if dialecto == "postgresql":
        if not (dpto_es_texto and mun_es_texto):
            db.session.execute(text("""
                ALTER TABLE tercero
                ALTER COLUMN dpto TYPE VARCHAR(2) USING
                    CASE
                        WHEN dpto IS NULL OR dpto::text = '' OR dpto::text ~ '^0+$' THEN NULL
                        WHEN dpto::text ~ '^[0-9]{1,2}$' THEN LPAD(dpto::text, 2, '0')
                        WHEN dpto::text ~ '^[0-9]+$' THEN LEFT(dpto::text, 2)
                        ELSE NULL
                    END,
                ALTER COLUMN mun TYPE VARCHAR(3) USING
                    CASE
                        WHEN mun IS NULL OR mun::text = '' OR mun::text ~ '^0+$' THEN NULL
                        WHEN mun::text ~ '^[0-9]{1,3}$' THEN LPAD(mun::text, 3, '0')
                        WHEN mun::text ~ '^[0-9]+$' THEN RIGHT(mun::text, 3)
                        ELSE NULL
                    END
            """))
        db.session.execute(text("""
            UPDATE tercero
            SET
                dpto = CASE
                    WHEN dpto IS NULL OR dpto = '' OR dpto ~ '^0+$' THEN NULL
                    WHEN dpto ~ '^[0-9]{1,2}$' THEN LPAD(dpto, 2, '0')
                    WHEN dpto ~ '^[0-9]+$' THEN LEFT(dpto, 2)
                    ELSE NULL
                END,
                mun = CASE
                    WHEN mun IS NULL OR mun = '' OR mun ~ '^0+$' THEN NULL
                    WHEN mun ~ '^[0-9]{1,3}$' THEN LPAD(mun, 3, '0')
                    WHEN mun ~ '^[0-9]+$' THEN RIGHT(mun, 3)
                    ELSE NULL
                END
        """))
        db.session.commit()
        return

    if dialecto == "sqlite" and not (dpto_es_texto and mun_es_texto):
        with db.engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE tercero_new (
                    id INTEGER NOT NULL,
                    usuario_id INTEGER NOT NULL,
                    nid VARCHAR(20) NOT NULL,
                    tdoc INTEGER,
                    dv INTEGER,
                    raz VARCHAR(450),
                    apl1 VARCHAR(60),
                    apl2 VARCHAR(60),
                    nom1 VARCHAR(60),
                    nom2 VARCHAR(60),
                    dir VARCHAR(200),
                    dpto VARCHAR(2),
                    mun VARCHAR(3),
                    pais INTEGER,
                    fuente VARCHAR(50),
                    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    FOREIGN KEY(usuario_id) REFERENCES usuario (id) ON DELETE CASCADE,
                    CONSTRAINT uq_tercero_usuario_nid UNIQUE (usuario_id, nid)
                )
            """))
            conn.execute(text("""
                INSERT INTO tercero_new (
                    id, usuario_id, nid, tdoc, dv, raz, apl1, apl2, nom1, nom2,
                    dir, dpto, mun, pais, fuente, actualizado_en
                )
                SELECT
                    id, usuario_id, nid, tdoc, dv, raz, apl1, apl2, nom1, nom2,
                    dir,
                    CASE
                        WHEN dpto IS NULL OR CAST(dpto AS TEXT) = '' OR CAST(dpto AS TEXT) = '0'
                        THEN NULL
                        ELSE printf('%02d', CAST(dpto AS INTEGER))
                    END,
                    CASE
                        WHEN mun IS NULL OR CAST(mun AS TEXT) = '' OR CAST(mun AS TEXT) = '0'
                        THEN NULL
                        ELSE printf('%03d', CAST(mun AS INTEGER))
                    END,
                    pais, fuente, actualizado_en
                FROM tercero
            """))
            conn.execute(text("DROP TABLE tercero"))
            conn.execute(text("ALTER TABLE tercero_new RENAME TO tercero"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tercero_usuario_id ON tercero (usuario_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tercero_nid ON tercero (nid)"))
