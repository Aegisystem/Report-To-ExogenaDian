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
    Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


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
    dpto: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mun: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
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
            "dpto": self.dpto,
            "mun": self.mun,
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
    """Historial de generaciones. Solo metadatos; los archivos quedan en /output."""
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
