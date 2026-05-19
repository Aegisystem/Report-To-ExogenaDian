"""Formato 1007 v9 - Ingresos recibidos."""
from __future__ import annotations

from typing import Any
import pandas as pd
from .base import BaseFormato


class Formato1007(BaseFormato):
    CODIGO = "1007"

    def _filas(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        df_g = self._filtrar_aplicables(df)
        filas = []
        for _nit, sub in self._agrupar_por_tercero(df_g).items():
            info = self._info_tercero(sub)
            ibru = self._suma_neta(sub, "base")
            if ibru <= 0:
                continue
            filas.append({
                "cpt": self.ctx.concepto_default_1007,
                "tdoc": info["tdoc"],
                "nid": info["nid"],
                "apl1": info["apl1"],
                "apl2": info["apl2"],
                "nom1": info["nom1"],
                "nom2": info["nom2"],
                "raz": info["raz"],
                "pais": info["pais"],
                "ibru": ibru,
                "dred": 0,
            })
        return filas
