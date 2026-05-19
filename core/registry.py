"""Catálogo persistente de tipos de documento y reglas de mapeo a formatos.

Cada Tipo de documento del MUISCA tiene:
  - categoria: factura / nota_credito / nota_debito / doc_equivalente /
               doc_soporte / nomina / ignorar
  - signo:     +1 (suma) o -1 (resta) en los acumulados

A qué formato va cada fila depende de (categoria, grupo):

  factura/equivalente/nota_credito/nota_debito:
    Recibido -> 1001, 1005 (y 5247, 5249 si participa en colab)
    Emitido  -> 1006, 1007 (y 5248, 5250 si participa en colab)

  doc_soporte (lo emite el comprador al comprar a no obligados):
    Recibido -> 1006, 1007 (alguien me lo emitió -> me compró -> es mi ingreso)
    Emitido  -> 1001, 1005 (yo lo emití -> compré a no obligado -> es mi gasto)

  nomina / ignorar:
    No se reporta en ningún formato.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_RUTA = Path(__file__).resolve().parent.parent / "config" / "conceptos.json"


def cargar() -> dict[str, Any]:
    if not _RUTA.exists():
        return {"tipos_documento": {}, "conceptos_por_defecto": {}, "pais_default": 169}
    with open(_RUTA, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar(data: dict[str, Any]) -> None:
    _RUTA.parent.mkdir(parents=True, exist_ok=True)
    with open(_RUTA, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def tipos_conocidos() -> set[str]:
    return set(cargar().get("tipos_documento", {}).keys())


def registrar_tipo(nombre: str, categoria: str, signo: int = 1) -> None:
    data = cargar()
    data.setdefault("tipos_documento", {})[nombre] = {"signo": signo, "categoria": categoria}
    guardar(data)


def categoria(nombre: str) -> str | None:
    info = cargar().get("tipos_documento", {}).get(nombre)
    return info["categoria"] if info else None


def signo(nombre: str) -> int:
    info = cargar().get("tipos_documento", {}).get(nombre)
    return info["signo"] if info else 1


def concepto_default(formato: str) -> int:
    return int(cargar().get("conceptos_por_defecto", {}).get(formato, 0))


def pais_default() -> int:
    return int(cargar().get("pais_default", 169))


CATEGORIAS_VALIDAS = [
    "factura",
    "nota_credito",
    "nota_debito",
    "doc_equivalente",
    "doc_soporte",
    "nomina",
    "ignorar",
]


# (categoria, grupo) -> formatos a los que aporta
_REGLAS_BASE: dict[tuple[str, str], list[str]] = {
    ("factura", "Recibido"):         ["1001", "1005"],
    ("factura", "Emitido"):          ["1006", "1007"],
    ("nota_debito", "Recibido"):     ["1001", "1005"],
    ("nota_debito", "Emitido"):      ["1006", "1007"],
    ("nota_credito", "Recibido"):    ["1001", "1005"],
    ("nota_credito", "Emitido"):     ["1006", "1007"],
    ("doc_equivalente", "Recibido"): ["1001", "1005"],
    ("doc_equivalente", "Emitido"):  ["1006", "1007"],
    # Documento soporte invertido: lo emite el comprador
    ("doc_soporte", "Recibido"):     ["1006", "1007"],
    ("doc_soporte", "Emitido"):      ["1001", "1005"],
    # Nómina y "ignorar" no van a ningún lado
    ("nomina", "Recibido"):          [],
    ("nomina", "Emitido"):           [],
    ("ignorar", "Recibido"):         [],
    ("ignorar", "Emitido"):          [],
}

# Cuando el informante participa en contrato de colaboración, además aportan a:
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
        extra = _REGLAS_COLABORACION.get((cat, g), [])
        return base + extra
    return base


def regla_para_formato(formato: str) -> set[tuple[str, str]]:
    """Devuelve el conjunto de (categoria, grupo) que aportan a un formato dado."""
    out = set()
    for (cat, grp), formatos in _REGLAS_BASE.items():
        if formato in formatos:
            out.add((cat, grp))
    for (cat, grp), formatos in _REGLAS_COLABORACION.items():
        if formato in formatos:
            out.add((cat, grp))
    return out
