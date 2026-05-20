"""Lector del XLSX de la DIAN MUISCA.

Normaliza encabezados (la fuente tiene problemas de codificación), tipa columnas,
detecta el NIT del informante (Recibido -> Receptor, Emitido -> Emisor)
y devuelve un DataFrame normalizado.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd


COLUMNAS_NUMERICAS = [
    "iva", "ica", "ic", "inc", "timbre", "inc_bolsas", "in_carbono",
    "in_combustibles", "ic_datos", "icl", "inpp", "ibua", "icui",
    "rete_iva", "rete_renta", "rete_ica", "total",
]


COLUMNAS_IMPUESTOS = [
    "iva", "ica", "ic", "inc", "timbre", "inc_bolsas", "in_carbono",
    "in_combustibles", "ic_datos", "icl", "inpp", "ibua", "icui",
]


@dataclass
class Informante:
    nit: str
    nombre: str


def _slug(s: str) -> str:
    if s is None:
        return ""
    txt = "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn")
    txt = txt.lower().strip()
    txt = re.sub(r"[^a-z0-9]+", "_", txt).strip("_")
    return txt


MAPEO_COLUMNAS = {
    "tipo_de_documento": "tipo_documento",
    "cufe_cude": "cufe",
    "folio": "folio",
    "prefijo": "prefijo",
    "divisa": "divisa",
    "forma_de_pago": "forma_pago",
    "medio_de_pago": "medio_pago",
    "fecha_emision": "fecha_emision",
    "fecha_recepcion": "fecha_recepcion",
    "nit_emisor": "nit_emisor",
    "nombre_emisor": "nombre_emisor",
    "nit_receptor": "nit_receptor",
    "nombre_receptor": "nombre_receptor",
    "iva": "iva",
    "ica": "ica",
    "ic": "ic",
    "inc": "inc",
    "timbre": "timbre",
    "inc_bolsas": "inc_bolsas",
    "in_carbono": "in_carbono",
    "in_combustibles": "in_combustibles",
    "ic_datos": "ic_datos",
    "icl": "icl",
    "inpp": "inpp",
    "ibua": "ibua",
    "icui": "icui",
    "rete_iva": "rete_iva",
    "rete_renta": "rete_renta",
    "rete_ica": "rete_ica",
    "total": "total",
    "estado": "estado",
    "grupo": "grupo",
}


def cargar_archivo(path: str, hoja: Optional[str] = None) -> tuple[pd.DataFrame, list[Informante]]:
    """Carga el XLSX, normaliza encabezados, tipa columnas, detecta informantes posibles."""
    df = pd.read_excel(path, sheet_name=hoja or 0, dtype=str, engine="openpyxl")

    # Normalizar nombres de columna
    nuevas = {}
    for col in df.columns:
        slug = _slug(col)
        nuevas[col] = MAPEO_COLUMNAS.get(slug, slug)
    df = df.rename(columns=nuevas)

    # Tipar fechas
    if "fecha_emision" in df.columns:
        df["fecha_emision"] = pd.to_datetime(df["fecha_emision"], dayfirst=True, errors="coerce")
    if "fecha_recepcion" in df.columns:
        df["fecha_recepcion"] = pd.to_datetime(df["fecha_recepcion"], dayfirst=True, errors="coerce")

    # Tipar numéricos
    for col in COLUMNAS_NUMERICAS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # Limpiar strings
    for col in ("tipo_documento", "grupo", "nit_emisor", "nombre_emisor",
                "nit_receptor", "nombre_receptor", "estado"):
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()

    # Suma de impuestos por fila (utilidad para generadores)
    impuestos_presentes = [c for c in COLUMNAS_IMPUESTOS if c in df.columns]
    df["impuestos_total"] = df[impuestos_presentes].sum(axis=1) if impuestos_presentes else 0.0

    # Base = Total - todos los impuestos
    df["base"] = df.get("total", 0) - df["impuestos_total"]

    # Detectar posibles informantes
    informantes = _detectar_informantes(df)

    return df, informantes


def _detectar_informantes(df: pd.DataFrame) -> list[Informante]:
    """Cuando Grupo=Emitido, el informante es el Emisor. Cuando Grupo=Recibido, el Receptor.
    Si solo hay un NIT único cumpliendo esa regla, es el informante.
    Si hay varios, los devolvemos para que el usuario elija."""
    pares: dict[str, str] = {}
    for _, row in df.iterrows():
        g = (row.get("grupo") or "").lower()
        if g == "emitido":
            nit = row.get("nit_emisor", "") or ""
            nom = row.get("nombre_emisor", "") or ""
        elif g == "recibido":
            nit = row.get("nit_receptor", "") or ""
            nom = row.get("nombre_receptor", "") or ""
        else:
            continue
        nit = str(nit).strip()
        if nit and nit not in pares:
            pares[nit] = str(nom).strip()

    return [Informante(nit=n, nombre=v) for n, v in pares.items()]


def filtrar_por_periodo(df: pd.DataFrame, ano: int, mes_inicio: int = 1, mes_fin: int = 12) -> pd.DataFrame:
    """Filtra por año y rango de meses sobre fecha_emision."""
    if "fecha_emision" not in df.columns:
        return df
    mask = (
        (df["fecha_emision"].dt.year == ano)
        & (df["fecha_emision"].dt.month >= mes_inicio)
        & (df["fecha_emision"].dt.month <= mes_fin)
    )
    return df[mask].copy()


def detectar_tipos_no_mapeados(df: pd.DataFrame, tipos_conocidos: set[str]) -> list[str]:
    """Devuelve los Tipo de documento que aparecen en el archivo pero no en el catálogo."""
    if "tipo_documento" not in df.columns:
        return []
    presentes = set(df["tipo_documento"].dropna().unique())
    return sorted(t for t in presentes - tipos_conocidos if "nomina" not in _slug(t))
