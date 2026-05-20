"""Catálogo de tipos de documento y reglas de mapeo a formatos (Postgres).

Cada usuario tiene su propio catálogo + un catálogo "global" (usuario_id NULL)
con los defaults del sistema. El lookup prefiere el del usuario y cae al global.

API pública compatible con la versión JSON:
  - tipos_conocidos() -> set[str]
  - registrar_tipo(nombre, categoria, signo=1)
  - catalogo_tipos() -> dict[str, dict]
  - categoria(nombre) -> str | None
  - signo(nombre) -> int
  - concepto_default(formato) -> int
  - pais_default() -> int
  - formatos_para(cat, grupo, incluir_colaboracion=False) -> list[str]
  - regla_para_formato(formato) -> set[(cat, grupo)]
"""
from __future__ import annotations

import unicodedata

from sqlalchemy import or_

from db import ConceptoDefault, TipoDocumento, db, usuario_actual_id


# ---------------- catálogo ----------------

CATEGORIAS_VALIDAS = [
    "factura", "nota_credito", "nota_debito",
    "doc_equivalente", "doc_soporte",
    "nomina", "ignorar",
]


_DEFAULTS_GLOBALES_TIPOS = [
    ("Factura electrónica", "factura", 1),
    ("Factura electronica", "factura", 1),
    ("Factura electrónica de contingencia", "factura", 1),
    ("Factura electronica de contingencia", "factura", 1),
    ("Nota de crédito electrónica", "nota_credito", -1),
    ("Nota de credito electronica", "nota_credito", -1),
    ("Nota débito electrónica", "nota_debito", 1),
    ("Nota debito electronica", "nota_debito", 1),
    ("Documento equivalente POS", "doc_equivalente", 1),
    ("Documento equivalente electrónico POS", "doc_equivalente", 1),
    ("Documento soporte electrónico", "doc_soporte", 1),
    ("Documento soporte electronico", "doc_soporte", 1),
    ("Documento soporte con no obligados", "doc_soporte", 1),
    ("Nómina electrónica", "nomina", 1),
    ("Nomina electronica", "nomina", 1),
    ("Nómina electrónica de ajuste", "nomina", 1),
    ("Nomina electronica de ajuste", "nomina", 1),
    ("Documento de nómina electrónica", "nomina", 1),
]

_DEFAULTS_CONCEPTOS = {
    "1001": 5016,
    "1007": 4001,
    "5247": 5016,
    "5248": 4001,
}

PAIS_DEFAULT = 169


def _normalizar_tipo(nombre: str | None) -> str:
    txt = "" if nombre is None else str(nombre)
    txt = "".join(c for c in unicodedata.normalize("NFD", txt) if unicodedata.category(c) != "Mn")
    return txt.lower().strip()


def es_tipo_nomina(nombre: str | None) -> bool:
    """Regla dura: cualquier tipo que diga nomina/nomina se ignora."""
    return "nomina" in _normalizar_tipo(nombre)


def _normalizar_mapeo_tipo(nombre: str, categoria: str, signo: int) -> tuple[str, int]:
    if es_tipo_nomina(nombre):
        return ("nomina", 1)
    return (categoria, int(signo))


def sembrar_catalogo_global() -> None:
    """Inserta los tipos globales si no existen. Idempotente."""
    for nombre, categoria, signo in _DEFAULTS_GLOBALES_TIPOS:
        existe = (
            db.session.query(TipoDocumento)
            .filter(TipoDocumento.usuario_id.is_(None), TipoDocumento.nombre == nombre)
            .first()
        )
        if not existe:
            db.session.add(TipoDocumento(usuario_id=None, nombre=nombre, categoria=categoria, signo=signo))
    db.session.commit()


def _query_tipo(nombre: str, usuario_id: int | None = None):
    """Busca un tipo por nombre. Prefiere el del usuario, cae al global."""
    if usuario_id is None:
        try:
            usuario_id = usuario_actual_id()
        except Exception:
            usuario_id = None

    q = db.session.query(TipoDocumento).filter(TipoDocumento.nombre == nombre)
    if usuario_id is not None:
        q = q.filter(or_(TipoDocumento.usuario_id == usuario_id, TipoDocumento.usuario_id.is_(None)))
        # Prioriza el del usuario
        return q.order_by(TipoDocumento.usuario_id.is_(None)).first()
    return q.filter(TipoDocumento.usuario_id.is_(None)).first()


def tipos_conocidos() -> set[str]:
    """Conjunto de nombres conocidos: tipos del usuario + globales."""
    try:
        uid = usuario_actual_id()
    except Exception:
        uid = None

    q = db.session.query(TipoDocumento.nombre)
    if uid is not None:
        q = q.filter(or_(TipoDocumento.usuario_id == uid, TipoDocumento.usuario_id.is_(None)))
    else:
        q = q.filter(TipoDocumento.usuario_id.is_(None))
    return {row[0] for row in q}


def catalogo_tipos(usuario_id: int | None = None) -> dict[str, dict[str, int | str]]:
    """Catálogo completo para el usuario, con tipos propios sobreescribiendo globales."""
    if usuario_id is None:
        try:
            usuario_id = usuario_actual_id()
        except Exception:
            usuario_id = None

    out: dict[str, dict[str, int | str]] = {}
    globales = (
        db.session.query(TipoDocumento)
        .filter(TipoDocumento.usuario_id.is_(None))
        .all()
    )
    for t in globales:
        categoria, signo = _normalizar_mapeo_tipo(t.nombre, t.categoria, t.signo)
        out[t.nombre] = {"categoria": categoria, "signo": signo}

    if usuario_id is not None:
        propios = (
            db.session.query(TipoDocumento)
            .filter(TipoDocumento.usuario_id == usuario_id)
            .all()
        )
        for t in propios:
            categoria, signo = _normalizar_mapeo_tipo(t.nombre, t.categoria, t.signo)
            out[t.nombre] = {"categoria": categoria, "signo": signo}

    return out


def registrar_tipo(nombre: str, categoria: str, signo: int = 1) -> None:
    """Registra/actualiza un tipo para el usuario actual."""
    uid = usuario_actual_id()
    categoria, signo = _normalizar_mapeo_tipo(nombre, categoria, signo)
    existente = (
        db.session.query(TipoDocumento)
        .filter_by(usuario_id=uid, nombre=nombre)
        .first()
    )
    if existente:
        existente.categoria = categoria
        existente.signo = signo
    else:
        db.session.add(TipoDocumento(usuario_id=uid, nombre=nombre, categoria=categoria, signo=signo))
    db.session.commit()


def categoria(nombre: str) -> str | None:
    if es_tipo_nomina(nombre):
        return "nomina"
    t = _query_tipo(nombre)
    return t.categoria if t else None


def signo(nombre: str) -> int:
    if es_tipo_nomina(nombre):
        return 1
    t = _query_tipo(nombre)
    return t.signo if t else 1


def concepto_default(formato: str) -> int:
    try:
        uid = usuario_actual_id()
    except Exception:
        return int(_DEFAULTS_CONCEPTOS.get(formato, 0))

    fila = (
        db.session.query(ConceptoDefault)
        .filter_by(usuario_id=uid, formato=formato)
        .first()
    )
    if fila:
        return int(fila.concepto)
    return int(_DEFAULTS_CONCEPTOS.get(formato, 0))


def set_concepto_default(formato: str, concepto: int) -> None:
    uid = usuario_actual_id()
    fila = (
        db.session.query(ConceptoDefault)
        .filter_by(usuario_id=uid, formato=formato)
        .first()
    )
    if fila:
        fila.concepto = int(concepto)
    else:
        db.session.add(ConceptoDefault(usuario_id=uid, formato=formato, concepto=int(concepto)))
    db.session.commit()


def pais_default() -> int:
    return PAIS_DEFAULT


# ---------------- reglas de mapeo (estáticas) ----------------

_REGLAS_BASE: dict[tuple[str, str], list[str]] = {
    ("factura", "Recibido"):         ["1001", "1005"],
    ("factura", "Emitido"):          ["1006", "1007"],
    ("nota_debito", "Recibido"):     ["1001", "1005"],
    ("nota_debito", "Emitido"):      ["1006", "1007"],
    ("nota_credito", "Recibido"):    ["1001", "1005"],
    ("nota_credito", "Emitido"):     ["1006", "1007"],
    ("doc_equivalente", "Recibido"): ["1001", "1005"],
    ("doc_equivalente", "Emitido"):  ["1006", "1007"],
    ("doc_soporte", "Recibido"):     ["1006", "1007"],
    ("doc_soporte", "Emitido"):      ["1001", "1005"],
    ("nomina", "Recibido"):          [],
    ("nomina", "Emitido"):           [],
    ("ignorar", "Recibido"):         [],
    ("ignorar", "Emitido"):          [],
}

_REGLAS_COLABORACION: dict[tuple[str, str], list[str]] = {
    ("factura", "Recibido"):         ["5247", "5249"],
    ("factura", "Emitido"):          ["5248", "5250"],
    ("nota_debito", "Recibido"):     ["5247", "5249"],
    ("nota_debito", "Emitido"):      ["5248", "5250"],
    ("nota_credito", "Recibido"):    ["5247", "5249"],
    ("nota_credito", "Emitido"):     ["5248", "5250"],
    ("doc_equivalente", "Recibido"): ["5247", "5249"],
    ("doc_equivalente", "Emitido"):  ["5248", "5250"],
    ("doc_soporte", "Recibido"):     ["5248", "5250"],
    ("doc_soporte", "Emitido"):      ["5247", "5249"],
}


def formatos_para(cat: str | None, grupo: str, incluir_colaboracion: bool = False) -> list[str]:
    if not cat:
        return []
    g = (grupo or "").strip()
    base = _REGLAS_BASE.get((cat, g), [])
    if incluir_colaboracion:
        return base + _REGLAS_COLABORACION.get((cat, g), [])
    return base


def regla_para_formato(formato: str) -> set[tuple[str, str]]:
    out = set()
    for (c, g), formatos in _REGLAS_BASE.items():
        if formato in formatos:
            out.add((c, g))
    for (c, g), formatos in _REGLAS_COLABORACION.items():
        if formato in formatos:
            out.add((c, g))
    return out
