"""Formato 5247 v1 - Pagos contratos colaboración empresarial.
Solo genera filas si el informante está marcado como participante. Si no, se entrega vacío.
"""
from __future__ import annotations

from typing import Any
import pandas as pd
from .base import BaseFormato


class Formato5247(BaseFormato):
    CODIGO = "5247"

    def _filas(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        if not self.ctx.es_participante_colaboracion:
            return []
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
                "tcon": self.ctx.tipo_contrato,
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
                "ivam": iva,
                "reprar": ret_renta,
                "rasre": 0,
                "repric": ret_iva,
                "rasnod": 0,
                "idfi": self.ctx.id_fideicomiso,
                "tdopa": self.ctx.tdoc_participante,
                "nidpa": self.ctx.nit_participante,
            })
        return filas
