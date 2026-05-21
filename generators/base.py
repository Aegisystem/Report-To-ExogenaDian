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
    tipo_contrato: int = 2
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
        self._tipos = registry.catalogo_tipos()

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

    def _categoria_tipo(self, tipo: str) -> str | None:
        if registry.es_tipo_nomina(tipo):
            return "nomina"
        info = self._tipos.get(tipo, {})
        cat = info.get("categoria")
        return str(cat) if cat else None

    def _signo_tipo(self, tipo: str) -> int:
        if registry.es_tipo_nomina(tipo):
            return 1
        return int(self._tipos.get(tipo, {}).get("signo", 1))

    def _filtrar_aplicables(self, df: pd.DataFrame) -> pd.DataFrame:
        """Devuelve solo las filas cuya (categoria, grupo) aporta a este formato."""
        if df.empty:
            return df
        es_colab = self.CODIGO.startswith("52")
        if es_colab != self.ctx.es_participante_colaboracion:
            return df.iloc[0:0].copy()
        if "tipo_documento" not in df.columns or "grupo" not in df.columns:
            return df.iloc[0:0].copy()

        out = df.copy()
        tipos = out["tipo_documento"].fillna("").astype(str).str.strip()
        grupos = out["grupo"].fillna("").astype(str).str.strip()
        categorias = tipos.map(self._categoria_tipo)
        signos = tipos.map(self._signo_tipo)
        mask = [(cat, grp) in self._reglas for cat, grp in zip(categorias, grupos)]
        out = out.loc[mask].copy()
        out["__categoria__"] = categorias.loc[out.index]
        out["__signo__"] = signos.loc[out.index]
        return out

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
        if cache and cache.get("tdoc"):
            try:
                tdoc = int(cache["tdoc"])
                info["tdoc"] = tdoc
            except (TypeError, ValueError):
                pass

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
            if tdoc == 13:
                info["dv"] = ""
            else:
                info["dv"] = (cache or {}).get("dv") if cache else helpers.calcular_dv(nid)
                if info["dv"] is None:
                    info["dv"] = helpers.calcular_dv(nid)
        if "pais" in campos:
            info["pais"] = (cache or {}).get("pais") or registry.pais_default()
        if "dir" in campos:
            info["dir"] = (cache or {}).get("dir", "") or ""
        if "dpto" in campos:
            info["dpto"] = helpers.normalizar_departamento((cache or {}).get("dpto"))
        if "mun" in campos:
            info["mun"] = helpers.normalizar_municipio((cache or {}).get("mun"))
        return info

    def _suma_neta(self, sub: pd.DataFrame, columna: str) -> float:
        """Suma 'columna' aplicando el signo del tipo de documento."""
        if columna not in sub.columns:
            return 0.0
        valores = pd.to_numeric(sub[columna], errors="coerce").fillna(0.0)
        if "__signo__" in sub.columns:
            signos = pd.to_numeric(sub["__signo__"], errors="coerce").fillna(1.0)
        else:
            tipos = sub.get("tipo_documento", pd.Series(index=sub.index, dtype=str)).fillna("").astype(str).str.strip()
            signos = tipos.map(self._signo_tipo)
        if "__categoria__" in sub.columns:
            aplicables = ~sub["__categoria__"].isin(("ignorar", "nomina"))
            valores = valores[aplicables]
            signos = signos[aplicables]
        return float((valores * signos).sum())

    def _sumas_positivas_y_devoluciones(self, sub: pd.DataFrame, columna: str) -> tuple[float, float]:
        """Separa valores con signo positivo de valores negativos como devoluciones."""
        if columna not in sub.columns:
            return (0.0, 0.0)
        valores = pd.to_numeric(sub[columna], errors="coerce").fillna(0.0)
        if "__signo__" in sub.columns:
            signos = pd.to_numeric(sub["__signo__"], errors="coerce").fillna(1.0)
        else:
            tipos = sub.get("tipo_documento", pd.Series(index=sub.index, dtype=str)).fillna("").astype(str).str.strip()
            signos = tipos.map(self._signo_tipo)
        if "__categoria__" in sub.columns:
            aplicables = ~sub["__categoria__"].isin(("ignorar", "nomina"))
            valores = valores[aplicables]
            signos = signos[aplicables]
        firmados = valores * signos
        ingresos = float(firmados[firmados > 0].sum())
        devoluciones = float((-firmados[firmados < 0]).sum())
        return (ingresos, devoluciones)

    def _tipar(self, df: pd.DataFrame) -> pd.DataFrame:
        for c in self.columnas:
            col = c["campo"]
            if col not in df.columns:
                continue
            tipo = c.get("tipo", "str")
            maxlen = c.get("max")
            if col == "dv":
                df[col] = df[col].apply(self._dv_o_blanco)
            elif tipo in ("long", "int"):
                df[col] = df[col].apply(lambda v: self._a_entero_no_neg(v))
            else:
                df[col] = df[col].fillna("").astype(str).str.slice(0, maxlen)
        return df

    @staticmethod
    def _dv_o_blanco(v):
        if v in (None, "") or (isinstance(v, float) and math.isnan(v)):
            return ""
        try:
            n = round(float(v))
        except (TypeError, ValueError):
            return ""
        return max(0, int(n))

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
