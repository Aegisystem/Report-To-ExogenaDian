"""Formato 1001 v10 - Pagos o abonos en cuenta y retenciones practicadas."""
from __future__ import annotations

from typing import Any
import pandas as pd
from .base import BaseFormato


class Formato1001(BaseFormato):
    CODIGO = "1001"

    def _filas(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        agregados = self._agregados_por_tercero(df, ["base", "iva", "rete_renta", "rete_iva"])
        filas = []
        for _, row in agregados.iterrows():
            info = self._info_tercero_valores(row["__nit_tercero__"], row["__nombre_tercero__"])
            base = row["base"]
            iva = row["iva"]
            ret_renta = row["rete_renta"]
            ret_iva = row["rete_iva"]
            if base <= 0 and ret_renta <= 0 and ret_iva <= 0:
                continue
            filas.append({
                "cpt": self.ctx.concepto_default_1001,
                "tdoc": info["tdoc"],
                "nid": info["nid"],
                "apl1": info["apl1"],
                "apl2": info["apl2"],
                "nom1": info["nom1"],
                "nom2": info["nom2"],
                "raz": info["raz"],
                "dir": info.get("dir", ""),
                "dpto": info.get("dpto", ""),
                "mun": info.get("mun", ""),
                "pais": info["pais"],
                "pago": base,
                "pnded": 0,
                "ided": iva,
                "inded": 0,
                "retp": ret_renta,
                "reta": 0,
                "comun": ret_iva,
                "ndom": 0,
            })
        return filas
