"""Formato 1006 v8 - Impuesto a las ventas generado e impuesto al consumo."""
from __future__ import annotations

from typing import Any
import pandas as pd
from .base import BaseFormato


class Formato1006(BaseFormato):
    CODIGO = "1006"

    def _filas(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        agregados = self._agregados_por_tercero(df, ["iva", "inc"])
        filas = []
        for _, row in agregados.iterrows():
            info = self._info_tercero_valores(row["__nit_tercero__"], row["__nombre_tercero__"])
            imp = row["iva"]
            inc = row["inc"]
            if imp <= 0 and inc <= 0:
                continue
            filas.append({
                "tdoc": info["tdoc"],
                "nid": info["nid"],
                "dv": info.get("dv", ""),
                "apl1": info["apl1"],
                "apl2": info["apl2"],
                "nom1": info["nom1"],
                "nom2": info["nom2"],
                "raz": info["raz"],
                "imp": imp,
                "iva": 0,
                "icon": inc,
            })
        return filas
