"""Formato 1006 v8 - Impuesto a las ventas generado e impuesto al consumo."""
from __future__ import annotations

from typing import Any
import pandas as pd
from .base import BaseFormato


class Formato1006(BaseFormato):
    CODIGO = "1006"

    def _filas(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        df_g = self._filtrar_aplicables(df)
        filas = []
        for _nit, sub in self._agrupar_por_tercero(df_g).items():
            info = self._info_tercero(sub)
            imp = self._suma_neta(sub, "iva")
            inc = self._suma_neta(sub, "inc")
            if imp <= 0 and inc <= 0:
                continue
            filas.append({
                "tdoc": info["tdoc"],
                "nid": info["nid"],
                "dv": info.get("dv", 0),
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
