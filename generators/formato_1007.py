"""Formato 1007 v9 - Ingresos recibidos."""
from __future__ import annotations

from typing import Any
import pandas as pd
from .base import BaseFormato


class Formato1007(BaseFormato):
    CODIGO = "1007"

    def _filas(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        agregados = self._agregados_pos_dev_por_tercero(df, "base")
        filas = []
        for _, row in agregados.iterrows():
            info = self._info_tercero_valores(row["__nit_tercero__"], row["__nombre_tercero__"])
            ibru, dred = row["positivo"], row["devolucion"]
            if ibru <= 0 and dred <= 0:
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
                "dred": dred,
            })
        return filas
