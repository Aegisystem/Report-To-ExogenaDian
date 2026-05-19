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
        df_g = self._filtrar_aplicables(df)
        filas = []
        for _nit, sub in self._agrupar_por_tercero(df_g).items():
            info = self._info_tercero(sub)
            base = self._suma_neta(sub, "base")
            iva = self._suma_neta(sub, "iva")
            ret_renta = self._suma_neta(sub, "rete_renta")
            ret_iva = self._suma_neta(sub, "rete_iva")
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
                "dpto": info.get("dpto", 0),
                "mun": info.get("mun", 0),
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
