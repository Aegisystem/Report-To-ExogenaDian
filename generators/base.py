"""Clase base para todos los generadores de formato exógena DIAN.

El agrupamiento por tercero ahora respeta las reglas (categoria, grupo)
definidas en core.registry — esto permite que un mismo formato consuma
filas de distinto Grupo según la categoría del documento (ej. doc soporte
emitido va a 1001 aunque los demás 1001 vengan de Recibidos).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from core import directorio, helpers, registry


_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "formatos.yaml"
_CONFIG: dict[str, Any] | None = None


def _config() -> dict[str, Any]:
    global _CONFIG
    if _CONFIG is None:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _CONFIG = yaml.safe_load(f)
    return _CONFIG


@dataclass
class ContextoInformante:
    nit: str
    razon_social: str
    ano_gravable: int
    mes_inicio: int = 1
    mes_fin: int = 12
    concepto_default_1001: int = 5016
    concepto_default_1007: int = 4001
    es_participante_colaboracion: bool = False
    tipo_contrato: int = 1
    nit_participante: str = ""
    tdoc_participante: int = 31
    id_fideicomiso: str = ""


def nit_tercero(row) -> str:
    """Devuelve el NIT del 'otro' lado de la operación según el Grupo."""
    g = (row.get("grupo") or "").lower()
    if g == "recibido":
        return str(row.get("nit_emisor", "")).strip()
    if g == "emitido":
        return str(row.get("nit_receptor", "")).strip()
    return ""


def nombre_tercero(row) -> str:
    g = (row.get("grupo") or "").lower()
    if g == "recibido":
        return str(row.get("nombre_emisor", "")).strip()
    if g == "emitido":
        return str(row.get("nombre_receptor", "")).strip()
    return ""


class BaseFormato:
    """Subclases definen CODIGO. Implementan _filas() devolviendo lista de dicts."""

    CODIGO: str = ""

    def __init__(self, ctx: ContextoInformante):
        self.ctx = ctx
        self.cfg = _config()["formatos"][self.CODIGO]
        self.columnas = self.cfg["columnas"]
        self._reglas = registry.regla_para_formato(self.CODIGO)

    # ---- API ----

    def generar(self, df: pd.DataFrame) -> pd.DataFrame:
        filas = self._filas(df)
        salida = pd.DataFrame(filas)
        if salida.empty:
            salida = pd.DataFrame(columns=[c["campo"] for c in self.columnas])
        cols_orden = [c["campo"] for c in self.columnas]
        for col in cols_orden:
            if col not in salida.columns:
                salida[col] = None
        salida = salida[cols_orden]
        salida = self._tipar(salida)
        return salida

    # ---- helpers comunes ----

    def _filtrar_aplicables(self, df: pd.DataFrame) -> pd.DataFrame:
        """Devuelve solo las filas cuya (categoria, grupo) aporta a este formato."""
        if df.empty:
            return df
        es_colab = self.CODIGO.startswith("52")

        def aplica(row):
            cat = registry.categoria(row.get("tipo_documento", ""))
            if not cat:
                return False
            grp = (row.get("grupo") or "").strip()
            # En formatos 52xx, solo aplican si el informante es participante
            if es_colab and not self.ctx.es_participante_colaboracion:
                return False
            return (cat, grp) in self._reglas

        mask = df.apply(aplica, axis=1)
        return df[mask].copy()

    def _agrupar_por_tercero(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        if df.empty:
            return {}
        df = df.copy()
        df["__nit_tercero__"] = df.apply(nit_tercero, axis=1)
        df["__nombre_tercero__"] = df.apply(nombre_tercero, axis=1)
        # Excluir filas del propio informante (autofacturación, etc.)
        df = df[df["__nit_tercero__"] != str(self.ctx.nit).strip()]
        grupos = {}
        for nit, sub in df.groupby("__nit_tercero__", dropna=False):
            nit = str(nit or "").strip()
            if not nit:
                continue
            grupos[nit] = sub
        return grupos

    def _info_tercero(self, sub: pd.DataFrame) -> dict[str, Any]:
        """Datos identificatorios del tercero. Consulta directorio si tiene cache."""
        nit_raw = sub["__nit_tercero__"].iloc[0]
        nombre = sub["__nombre_tercero__"].iloc[0]
        nid = helpers.normalizar_nit(nit_raw)
        tdoc = helpers.inferir_tipo_documento(nid)

        info: dict[str, Any] = {"nid": nid, "tdoc": tdoc}

        cache = directorio.lookup(nid)

        if helpers.es_persona_natural(tdoc):
            if cache and (cache.get("apl1") or cache.get("nom1")):
                info.update({
                    "apl1": cache.get("apl1", "") or "",
                    "apl2": cache.get("apl2", "") or "",
                    "nom1": cache.get("nom1", "") or "",
                    "nom2": cache.get("nom2", "") or "",
                    "raz": "",
                })
            else:
                apl1, apl2, nom1, nom2 = helpers.split_nombre_persona(nombre)
                info.update({"apl1": apl1, "apl2": apl2, "nom1": nom1, "nom2": nom2, "raz": ""})
        else:
            razon = (cache or {}).get("raz") or nombre
            info.update({
                "apl1": "", "apl2": "", "nom1": "", "nom2": "",
                "raz": helpers.limpiar_texto(razon, 450),
            })

        campos = {c["campo"] for c in self.columnas}
        if "dv" in campos:
            info["dv"] = (cache or {}).get("dv") if cache else helpers.calcular_dv(nid)
            if info["dv"] is None:
                info["dv"] = helpers.calcular_dv(nid)
        if "pais" in campos:
            info["pais"] = (cache or {}).get("pais") or registry.pais_default()
        if "dir" in campos:
            info["dir"] = (cache or {}).get("dir", "") or ""
        if "dpto" in campos:
            info["dpto"] = (cache or {}).get("dpto") or 0
        if "mun" in campos:
            info["mun"] = (cache or {}).get("mun") or 0
        return info

    def _suma_neta(self, sub: pd.DataFrame, columna: str) -> float:
        """Suma 'columna' aplicando el signo del tipo de documento."""
        if columna not in sub.columns:
            return 0.0
        total = 0.0
        for _, row in sub.iterrows():
            cat = registry.categoria(row.get("tipo_documento", ""))
            if cat in ("ignorar", "nomina"):
                continue
            s = registry.signo(row.get("tipo_documento", ""))
            total += float(row.get(columna, 0) or 0) * s
        return total

    def _tipar(self, df: pd.DataFrame) -> pd.DataFrame:
        for c in self.columnas:
            col = c["campo"]
            if col not in df.columns:
                continue
            tipo = c.get("tipo", "str")
            maxlen = c.get("max")
            if tipo in ("long", "int"):
                df[col] = df[col].apply(lambda v: self._a_entero_no_neg(v))
            else:
                df[col] = df[col].fillna("").astype(str).str.slice(0, maxlen)
        return df

    @staticmethod
    def _a_entero_no_neg(v) -> int:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return 0
        try:
            n = round(float(v))
        except (TypeError, ValueError):
            return 0
        return max(0, int(n))

    def _filas(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        raise NotImplementedError
